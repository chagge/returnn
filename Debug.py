
import os
import sys


global_exclude_thread_ids = set()

def auto_exclude_all_new_threads(func):
  def wrapped(*args, **kwargs):
    old_threads = set(sys._current_frames().keys())
    res = func(*args, **kwargs)
    new_threads = set(sys._current_frames().keys())
    new_threads -= old_threads
    global_exclude_thread_ids.update(new_threads)
    return res
  return wrapped


def dumpAllThreadTracebacks(exclude_thread_ids=set()):
  import better_exchook
  import threading

  if hasattr(sys, "_current_frames"):
    print ""
    threads = {t.ident: t for t in threading.enumerate()}
    for tid, stack in sys._current_frames().items():
      if tid in exclude_thread_ids: continue
      # This is a bug in earlier Python versions.
      # http://bugs.python.org/issue17094
      # Note that this leaves out all threads not created via the threading module.
      if tid not in threads: continue
      print "Thread %s:" % threads.get(tid, "unnamed with id %i" % tid)
      if tid in global_exclude_thread_ids:
        print "(Auto-ignored traceback.)"
      else:
        better_exchook.print_tb(stack)
      print ""
  else:
    print "Does not have sys._current_frames, cannot get thread tracebacks."


def initBetterExchook():
  import thread
  import threading
  import better_exchook
  import pdb

  def excepthook(exc_type, exc_obj, exc_tb):
    try:
      is_main_thread = isinstance(threading.currentThread(), threading._MainThread)
    except Exception:  # Can happen at a very late state while quitting.
      if exc_type is KeyboardInterrupt:
        return
    else:
      if is_main_thread:
        if exc_type is KeyboardInterrupt and getattr(sys, "exited", False):
          # Got SIGINT twice. Can happen.
          return
        # An unhandled exception in the main thread. This means that we are going to quit now.
        sys.exited = True
    print "Unhandled exception %s in thread %s, proc %i." % (exc_type, threading.currentThread(), os.getpid())
    if exc_type is KeyboardInterrupt:
      return

    if isinstance(threading.currentThread(), threading._MainThread):
      main_thread_id = thread.get_ident()
      if not isinstance(exc_type, Exception):
        # We are the main thread and we got an exit-exception. This is likely fatal.
        # This usually means an exit. (We ignore non-daemon threads and procs here.)
        # Print the stack of all other threads.
        dumpAllThreadTracebacks({main_thread_id})

    better_exchook.better_exchook(exc_type, exc_obj, exc_tb)

  sys.excepthook = excepthook


def initFaulthandler(sigusr1_chain=False):
  """
  :param bool sigusr1_chain: whether the default SIGUSR1 handler should also be called.
  """
  try:
    import faulthandler
  except ImportError, e:
    print "faulthandler import error. %s" % e
    return
  # Only enable if not yet enabled -- otherwise, leave it in its current state.
  if not faulthandler.is_enabled():
    faulthandler.enable()
    if os.name != 'nt':
      import signal
      faulthandler.register(signal.SIGUSR1, all_threads=True, chain=sigusr1_chain)


@auto_exclude_all_new_threads
def initIPythonKernel():
  # You can remotely connect to this kernel. See the output on stdout.
  try:
    import IPython.kernel.zmq.ipkernel
    from IPython.kernel.zmq.ipkernel import Kernel
    from IPython.kernel.zmq.heartbeat import Heartbeat
    from IPython.kernel.zmq.session import Session
    from IPython.kernel import write_connection_file
    import zmq
    from zmq.eventloop import ioloop
    from zmq.eventloop.zmqstream import ZMQStream
    IPython.kernel.zmq.ipkernel.signal = lambda sig, f: None  # Overwrite.
  except ImportError, e:
    print "IPython import error, cannot start IPython kernel. %s" % e
    return
  import atexit
  import socket
  import logging
  import threading

  # Do in mainthread to avoid history sqlite DB errors at exit.
  # https://github.com/ipython/ipython/issues/680
  assert isinstance(threading.currentThread(), threading._MainThread)
  try:
    ip = socket.gethostbyname(socket.gethostname())
    connection_file = "ipython-kernel-%s-%s.json" % (ip, os.getpid())
    def cleanup_connection_file():
      try:
        os.remove(connection_file)
      except (IOError, OSError):
        pass
    atexit.register(cleanup_connection_file)

    logger = logging.Logger("IPython")
    logger.addHandler(logging.NullHandler())
    session = Session(username=u'kernel')

    context = zmq.Context.instance()
    transport = "tcp"
    addr = "%s://%s" % (transport, ip)
    shell_socket = context.socket(zmq.ROUTER)
    shell_port = shell_socket.bind_to_random_port(addr)
    iopub_socket = context.socket(zmq.PUB)
    iopub_port = iopub_socket.bind_to_random_port(addr)
    control_socket = context.socket(zmq.ROUTER)
    control_port = control_socket.bind_to_random_port(addr)

    hb_ctx = zmq.Context()
    heartbeat = Heartbeat(hb_ctx, (transport, ip, 0))
    hb_port = heartbeat.port
    heartbeat.start()

    shell_stream = ZMQStream(shell_socket)
    control_stream = ZMQStream(control_socket)

    kernel = Kernel(session=session,
                    shell_streams=[shell_stream, control_stream],
                    iopub_socket=iopub_socket,
                    log=logger)

    write_connection_file(connection_file,
                          shell_port=shell_port, iopub_port=iopub_port, control_port=control_port, hb_port=hb_port,
                          ip=ip)

    #print "To connect another client to this IPython kernel, use:", \
    #      "ipython console --existing %s" % connection_file
  except Exception, e:
    print "Exception while initializing IPython ZMQ kernel. %s" % e
    return

  def ipython_thread():
    kernel.start()
    try:
      ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
      pass

  thread = threading.Thread(target=ipython_thread, name="IPython kernel")
  thread.daemon = True
  thread.start()


def initCudaNotInMainProcCheck():
  import TaskSystem
  import theano.sandbox.cuda as cuda
  if cuda.use.device_number is not None:
    print "CUDA already initialized in proc", os.getpid()
    return
  use_original = cuda.use
  def use_wrapped(device, **kwargs):
    print "CUDA.use", device, "in proc", os.getpid()
    #assert not TaskSystem.isMainProcess, "multiprocessing is set to True in your config but the main proc tries to use CUDA"
    use_original(device=device, **kwargs)
  cuda.use = use_wrapped
  cuda.use.device_number = None


def debug_shell(user_ns=None, user_global_ns=None, exit_afterwards=True):
  print "Debug shell:"
  from Util import ObjAsDict
  import DebugHelpers
  user_global_ns_new = dict(ObjAsDict(DebugHelpers).items())
  if user_global_ns:
    user_global_ns_new.update(user_global_ns)  # may overwrite vars from DebugHelpers
  user_global_ns_new["debug"] = DebugHelpers  # make this available always
  print "Available debug functions/utils (via DebugHelpers):"
  for k, v in sorted(vars(DebugHelpers).items()):
    if k[:1] == "_": continue
    print "  %s (%s)" % (k, type(v))
  print "Also DebugHelpers available as 'debug'."
  if not user_ns:
    user_ns = {}
  if user_ns:
    print "Locals:"
    for k, v in sorted(user_ns.items()):
      print "  %s (%s)" % (k, type(v))
  import better_exchook
  better_exchook.debug_shell(user_ns, user_global_ns_new)
  if exit_afterwards:
    print "Debug shell exit. Exit now."
    sys.exit(1)

