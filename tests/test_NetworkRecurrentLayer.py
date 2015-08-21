
import theano
import numpy
from NetworkBaseLayer import Container, SourceLayer
from NetworkRecurrentLayer import RecurrentUnitLayer

Container.initialize_rng()

# TODO more sane data
source = SourceLayer(n_out=2, x_out=theano.shared(numpy.array([1.0], dtype='float32'), name="x"))
index = theano.shared(numpy.array([[1]]), name="i")


def test_RecurrentUnitLayer_init():
  RecurrentUnitLayer(n_out=3, sources=[source], index=index)

def test_RecurrentUnitLayer_init_sampling2():
  RecurrentUnitLayer(n_out=3, sources=[source], index=index, sampling=2)