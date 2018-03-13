"""Unit tests for image deconvolution vis MSMFS


"""
import logging
import os
import unittest

import astropy.units as u
import numpy
from astropy.coordinates import SkyCoord

from arl.data.parameters import set_parameters
from arl.data.polarisation import PolarisationFrame
from arl.image.deconvolution import deconvolve_cube, restore_cube
from arl.image.operations import export_image_to_fits, create_image_from_array
from arl.imaging.base import predict_2d, invert_2d, create_image_from_visibility
from arl.util.testing_support import create_low_test_image_from_gleam, create_low_test_beam, create_named_configuration
from arl.visibility.base import create_visibility

log = logging.getLogger(__name__)


class TestImageDeconvolutionMSMFS(unittest.TestCase):
    def setUp(self):
        self.dir = './test_results'
        os.makedirs(self.dir, exist_ok=True)
        self.niter = 1000
        self.lowcore = create_named_configuration('LOWBD2-CORE')
        self.nchan = 5
        self.times = (numpy.pi / 12.0) * numpy.linspace(-3.0, 3.0, 7)
        self.frequency = numpy.linspace(0.9e8, 1.1e8, self.nchan)
        self.channel_bandwidth = numpy.array(self.nchan * [self.frequency[1] - self.frequency[0]])
        self.phasecentre = SkyCoord(ra=+0.0 * u.deg, dec=-45.0 * u.deg, frame='icrs', equinox='J2000')
        self.vis = create_visibility(self.lowcore, self.times, self.frequency, self.channel_bandwidth,
                                     phasecentre=self.phasecentre, weight=1.0,
                                     polarisation_frame=PolarisationFrame('stokesI'))
        self.vis.data['vis'] *= 0.0
        
        # Create model
        self.test_model = create_low_test_image_from_gleam(flux_limit=10.0, npixel=512, cellsize=0.001,
                                                           phasecentre=self.vis.phasecentre,
                                                           frequency=self.frequency,
                                                           channel_bandwidth=self.channel_bandwidth)
        beam = create_low_test_beam(self.test_model)
        export_image_to_fits(beam, "%s/test_deconvolve_mmclean_beam.fits" % self.dir)
        self.test_model.data *= beam.data
        export_image_to_fits(self.test_model, "%s/test_deconvolve_mmclean_model.fits" % self.dir)
        self.vis = predict_2d(self.vis, self.test_model)
        assert numpy.max(numpy.abs(self.vis.vis)) > 0.0
        self.model = create_image_from_visibility(self.vis, npixel=512, cellsize=0.001, nchan=self.nchan)
        self.dirty, sumwt = invert_2d(self.vis, self.model)
        self.psf, sumwt = invert_2d(self.vis, self.model, dopsf=True)
        export_image_to_fits(self.dirty, "%s/test_deconvolve_mmclean_dirty.fits" % self.dir)
        export_image_to_fits(self.psf, "%s/test_deconvolve_mmclean_psf.fits" % self.dir)
        window = numpy.ones(shape=self.model.shape, dtype=numpy.bool)
        window[..., 129:384, 129:384] = True
        self.innerquarter = create_image_from_array(window, self.model.wcs,
                                                    polarisation_frame=PolarisationFrame('stokesI'))
        self.ini = '%s/test_deconvolution_msmfs_config.ini' % self.dir
    
    def test_deconvolve_mmclean_no_taylor(self):
        set_parameters(self.ini, {'niter': self.niter, 'gain': 0.7, 'algorithm': 'mmclean', 'scales': [0, 30, 10],
                                  'threshold': 0.01, 'nmoments': 1, 'findpeak': 'ARL', 'window': 'quarter'},
                       'deconvolution')
        self.comp, self.residual = deconvolve_cube(self.dirty, self.psf, self.ini)
        export_image_to_fits(self.comp, "%s/test_deconvolve_mmclean_notaylor-comp.fits" % self.dir)
        export_image_to_fits(self.residual, "%s/test_deconvolve_mmclean_notaylor-residual.fits" % self.dir)
        self.cmodel = restore_cube(self.comp, self.psf, self.residual)
        export_image_to_fits(self.cmodel, "%s/test_deconvolve_mmclean_notaylor-clean.fits" % self.dir)
        assert numpy.max(self.residual.data) < 4.0
    
    def test_deconvolve_mmclean_no_taylor_noscales(self):
        set_parameters(self.ini, {'niter': 10000, 'gain': 0.1, 'algorithm': 'mmclean', 'scales': [0],
                                  'threshold': 0.01, 'nmoments': 1, 'findpeak': 'ARL', 'window': 'quarter'},
                       'deconvolution')
        self.comp, self.residual = deconvolve_cube(self.dirty, self.psf, self.ini)
        export_image_to_fits(self.comp, "%s/test_deconvolve_mmclean_notaylor_noscales-comp.fits" % self.dir)
        export_image_to_fits(self.residual, "%s/test_deconvolve_mmclean_notaylor_noscales-residual.fits" % self.dir)
        self.cmodel = restore_cube(self.comp, self.psf, self.residual)
        export_image_to_fits(self.cmodel, "%s/test_deconvolve_mmclean_notaylor_noscales-clean.fits" % self.dir)
        assert numpy.max(self.residual.data) < 8.0

    def test_deconvolve_mmclean_linear(self):
        set_parameters(self.ini, {'niter': self.niter, 'gain': 0.7, 'algorithm': 'mmclean', 'scales': [0, 3, 10],
                                  'threshold': 0.01, 'nmoments': 2, 'findpeak': 'ARL', 'window': 'quarter'},
                       'deconvolution')
        self.comp, self.residual = deconvolve_cube(self.dirty, self.psf, self.ini)
        export_image_to_fits(self.comp, "%s/test_deconvolve_mmclean_linear-comp.fits" % self.dir)
        export_image_to_fits(self.residual, "%s/test_deconvolve_mmclean_linear-residual.fits" % self.dir)
        self.cmodel = restore_cube(self.comp, self.psf, self.residual)
        export_image_to_fits(self.cmodel, "%s/test_deconvolve_mmclean_linear-clean.fits" % self.dir)
        assert numpy.max(self.residual.data) < 4.0
    
    def test_deconvolve_mmclean_linear_noscales(self):
        set_parameters(self.ini, {'niter': 10000, 'gain': 0.1, 'algorithm': 'mmclean', 'scales': [0],
                                  'threshold': 0.01, 'nmoments': 2, 'findpeak': 'ARL', 'window': 'quarter'},
                       'deconvolution')
        self.comp, self.residual = deconvolve_cube(self.dirty, self.psf, self.ini)
        export_image_to_fits(self.comp, "%s/test_deconvolve_mmclean_linear_noscales-comp.fits" % self.dir)
        export_image_to_fits(self.residual, "%s/test_deconvolve_mmclean_linear_noscales-residual.fits" % self.dir)
        self.cmodel = restore_cube(self.comp, self.psf, self.residual)
        export_image_to_fits(self.cmodel, "%s/test_deconvolve_mmclean_linear_noscales-clean.fits" % self.dir)
        assert numpy.max(self.residual.data) < 4.0
    
    def test_deconvolve_mmclean_quadratic(self):
        set_parameters(self.ini, {'niter': self.niter, 'gain': 0.7, 'algorithm': 'mmclean', 'scales': [0, 3, 10],
                                  'threshold': 0.01, 'nmoments': 2, 'findpeak': 'ARL', 'window': 'quarter'},
                       'deconvolution')
        self.comp, self.residual = deconvolve_cube(self.dirty, self.psf, self.ini)
        export_image_to_fits(self.comp, "%s/test_deconvolve_mmclean_quadratic-comp.fits" % self.dir)
        export_image_to_fits(self.residual, "%s/test_deconvolve_mmclean_quadratic-residual.fits" % self.dir)
        self.cmodel = restore_cube(self.comp, self.psf, self.residual)
        export_image_to_fits(self.cmodel, "%s/test_deconvolve_mmclean_quadratic-clean.fits" % self.dir)
        assert numpy.max(self.residual.data) < 4.0
    
    def test_deconvolve_mmclean_quadratic_noscales(self):
        set_parameters(self.ini, {'niter': 10000, 'gain': 0.1, 'algorithm': 'mmclean', 'scales': [0],
                                  'threshold': 0.01, 'nmoments': 2, 'findpeak': 'ARL', 'window': 'quarter'},
                       'deconvolution')
        self.comp, self.residual = deconvolve_cube(self.dirty, self.psf, self.ini)
        export_image_to_fits(self.comp, "%s/test_deconvolve_mmclean_quadratic_noscales-comp.fits" % self.dir)
        export_image_to_fits(self.residual, "%s/test_deconvolve_mmclean_quadratic_noscales-residual.fits" % self.dir)
        self.cmodel = restore_cube(self.comp, self.psf, self.residual)
        export_image_to_fits(self.cmodel, "%s/test_deconvolve_mmclean_quadratic_noscales-clean.fits" % self.dir)
        assert numpy.max(self.residual.data) < 4.0
    
    def test_deconvolve_mmclean_quadratic_psf(self):
        set_parameters(self.ini, {'niter': self.niter, 'gain': 0.1, 'algorithm': 'mmclean', 'scales': [0],
                                  'threshold': 0.01, 'nmoments': 2, 'findpeak': 'ARL', 'window': 'quarter',
                                  'psf_support': 32},
                       'deconvolution')
        self.comp, self.residual = deconvolve_cube(self.dirty, self.psf, self.ini)
        export_image_to_fits(self.comp, "%s/test_deconvolve_mmclean_quadratic_psf-comp.fits" % self.dir)
        export_image_to_fits(self.residual, "%s/test_deconvolve_mmclean_quadratic_psf-residual.fits" % self.dir)
        self.cmodel = restore_cube(self.comp, self.psf, self.residual)
        export_image_to_fits(self.cmodel, "%s/test_deconvolve_mmclean_quadratic_psf-clean.fits" % self.dir)
        assert numpy.max(self.residual.data) < 4.0


if __name__ == '__main__':
    unittest.main()
