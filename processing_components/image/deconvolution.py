""" Image deconvolution functions

The standard deconvolution algorithms are provided:

    hogbom: Hogbom CLEAN See: Hogbom CLEAN A&A Suppl, 15, 417, (1974)
    
    msclean: MultiScale CLEAN See: Cornwell, T.J., Multiscale CLEAN (IEEE Journal of Selected Topics in Sig Proc,
    2008 vol. 2 pp. 793-801)

    mfsmsclean: MultiScale Multi-Frequency See: U. Rau and T. J. Cornwell, “A multi-scale multi-frequency
    deconvolution algorithm for synthesis imaging in radio interferometry,” A&A 532, A71 (2011).

For example to make dirty image and PSF, deconvolve, and then restore::

    model = create_image_from_visibility(vt, cellsize=0.001, npixel=256)
    dirty, sumwt = invert_2d(vt, model)
    psf, sumwt = invert_2d(vt, model, dopsf=True)

    comp, residual = deconvolve_cube(dirty, psf, niter=1000, threshold=0.001, fracthresh=0.01, window='quarter',
                                 gain=0.7, algorithm='msclean', scales=[0, 3, 10, 30])

    restored = restore_cube(comp, psf, residual)

"""

import logging

import numpy
from astropy.convolution import Gaussian2DKernel, convolve
from photutils import fit_2dgaussian

from data_models.memory_data_models import Image
from data_models.parameters import get_parameter
from libs.image.cleaners import hogbom, msclean, msmfsclean
from libs.image.operations import create_image_from_array, copy_image
from ..image.operations import calculate_image_frequency_moments, calculate_image_from_frequency_moments

log = logging.getLogger(__name__)


def deconvolve_cube(dirty: Image, psf: Image, prefix='', **kwargs) -> (Image, Image):
    """ Clean using a variety of algorithms
    
    Functions that clean a dirty image using a point spread function. The algorithms available are:
    
    hogbom: Hogbom CLEAN See: Hogbom CLEAN A&A Suppl, 15, 417, (1974)
    
    msclean: MultiScale CLEAN See: Cornwell, T.J., Multiscale CLEAN (IEEE Journal of Selected Topics in Sig Proc,
    2008 vol. 2 pp. 793-801)

    mfsmsclean, msmfsclean, mmclean: MultiScale Multi-Frequency See: U. Rau and T. J. Cornwell,
    “A multi-scale multi-frequency deconvolution algorithm for synthesis imaging in radio interferometry,” A&A 532,
    A71 (2011).
    
    For example::
    
        comp, residual = deconvolve_cube(dirty, psf, niter=1000, gain=0.7, algorithm='msclean',
                                         scales=[0, 3, 10, 30], threshold=0.01)
                                         
    For the MFS clean, the psf must have number of channels >= 2 * nmoments
    
    :param dirty: Image dirty image
    :param psf: Image Point Spread Function
    :param window: Window image (Bool) - clean where True
    :param algorithm: Cleaning algorithm: 'msclean'|'hogbom'|'mfsmsclean'
    :param gain: loop gain (float) 0.7
    :param threshold: Clean threshold (0.0)
    :param fractional_threshold: Fractional threshold (0.01)
    :param scales: Scales (in pixels) for multiscale ([0, 3, 10, 30])
    :param nmoments: Number of frequency moments (default 3)
    :param findpeak: Method of finding peak in mfsclean: 'Algorithm1'|'ASKAPSoft'|'CASA'|'ARL', Default is ARL.
    :return: componentimage, residual
    
    """
    
    assert isinstance(dirty, Image), dirty
    assert isinstance(psf, Image), psf
    
    window_shape = get_parameter(kwargs, 'window_shape', None)
    if window_shape == 'quarter':
        qx = dirty.shape[3] // 4
        qy = dirty.shape[2] // 4
        window = numpy.zeros_like(dirty.data)
        window[..., (qy + 1):3 * qy, (qx + 1):3 * qx] = 1.0
        log.info('deconvolve_cube %s: Cleaning inner quarter of each sky plane' % prefix)
    else:
        window = None
    
    psf_support = get_parameter(kwargs, 'psf_support', max(dirty.shape[2] // 2, dirty.shape[3] // 2))
    if (psf_support <= psf.shape[2] // 2) and ((psf_support <= psf.shape[3] // 2)):
        centre = [psf.shape[2] // 2, psf.shape[3] // 2]
        psf.data = psf.data[..., (centre[0] - psf_support):(centre[0] + psf_support),
                   (centre[1] - psf_support):(centre[1] + psf_support)]
        log.info('deconvolve_cube %s: PSF support = +/- %d pixels' % (prefix, psf_support))
        log.info('deconvolve_cube %s: PSF shape %s' % (prefix, str(psf.data.shape)))
    
    algorithm = get_parameter(kwargs, 'algorithm', 'msclean')

    if algorithm == 'msclean':
        log.info("deconvolve_cube %s: Multi-scale clean of each polarisation and channel separately" %
                 prefix)
        gain = get_parameter(kwargs, 'gain', 0.7)
        assert 0.0 < gain < 2.0, "Loop gain must be between 0 and 2"
        thresh = get_parameter(kwargs, 'threshold', 0.0)
        assert thresh >= 0.0
        niter = get_parameter(kwargs, 'niter', 100)
        assert niter > 0
        scales = get_parameter(kwargs, 'scales', [0, 3, 10, 30])
        fracthresh = get_parameter(kwargs, 'fractional_threshold', 0.01)
        assert 0.0 < fracthresh < 1.0
        
        comp_array = numpy.zeros_like(dirty.data)
        residual_array = numpy.zeros_like(dirty.data)
        for channel in range(dirty.data.shape[0]):
            for pol in range(dirty.data.shape[1]):
                if psf.data[channel, pol, :, :].max():
                    log.info("deconvolve_cube %s: Processing pol %d, channel %d" % (prefix, pol, channel))
                    if window is None:
                        comp_array[channel, pol, :, :], residual_array[channel, pol, :, :] = \
                            msclean(dirty.data[channel, pol, :, :], psf.data[channel, pol, :, :],
                                    None, gain, thresh, niter, scales, fracthresh, prefix)
                    else:
                        comp_array[channel, pol, :, :], residual_array[channel, pol, :, :] = \
                            msclean(dirty.data[channel, pol, :, :], psf.data[channel, pol, :, :],
                                    window[channel, pol, :, :], gain, thresh, niter, scales, fracthresh,
                                    prefix)
                else:
                    log.info("deconvolve_cube %s: Skipping pol %d, channel %d" % (prefix, pol, channel))
        
        comp_image = create_image_from_array(comp_array, dirty.wcs, dirty.polarisation_frame)
        residual_image = create_image_from_array(residual_array, dirty.wcs, dirty.polarisation_frame)
    
    elif algorithm == 'msmfsclean' or algorithm == 'mfsmsclean' or algorithm == 'mmclean':
        findpeak = get_parameter(kwargs, "findpeak", 'ARL')
        
        log.info("deconvolve_cube %s: Multi-scale multi-frequency clean of each polarisation separately"
                 % prefix)
        nmoments = get_parameter(kwargs, "nmoments", 3)
        assert nmoments > 0, "Number of frequency moments must be greater than zero"
        nchan = dirty.shape[0]
        assert nchan > 2 * nmoments, "Require nchan %d > 2 * nmoments %d" % (nchan, 2 * nmoments)
        dirty_taylor = calculate_image_frequency_moments(dirty, nmoments=nmoments)
        psf_taylor = calculate_image_frequency_moments(psf, nmoments=2 * nmoments)
        psf_peak = numpy.max(psf_taylor.data)
        dirty_taylor.data /= psf_peak
        psf_taylor.data /= psf_peak
        log.info("deconvolve_cube %s: Shape of Dirty moments image %s" %
                 (prefix, str(dirty_taylor.shape)))
        log.info("deconvolve_cube %s: Shape of PSF moments image %s" % (prefix, str(psf_taylor.shape)))
        gain = get_parameter(kwargs, 'gain', 0.7)
        assert 0.0 < gain < 2.0, "Loop gain must be between 0 and 2"
        thresh = get_parameter(kwargs, 'threshold', 0.0)
        assert thresh >= 0.0
        niter = get_parameter(kwargs, 'niter', 100)
        assert niter > 0
        scales = get_parameter(kwargs, 'scales', [0, 3, 10, 30])
        fracthresh = get_parameter(kwargs, 'fractional_threshold', 0.1)
        assert 0.0 < fracthresh < 1.0
        
        comp_array = numpy.zeros(dirty_taylor.data.shape)
        residual_array = numpy.zeros(dirty_taylor.data.shape)
        for pol in range(dirty_taylor.data.shape[1]):
            if psf_taylor.data[0, pol, :, :].max():
                log.info("deconvolve_cube %s: Processing pol %d" % (prefix, pol))
                if window is None:
                    comp_array[:, pol, :, :], residual_array[:, pol, :, :] = \
                        msmfsclean(dirty_taylor.data[:, pol, :, :], psf_taylor.data[:, pol, :, :],
                                   None, gain, thresh, niter, scales, fracthresh, findpeak, prefix)
                else:
                    qx = dirty.shape[3] // 4
                    qy = dirty.shape[2] // 4
                    window_taylor = numpy.zeros_like(dirty_taylor.data)
                    window_taylor[..., (qy + 1):3 * qy, (qx + 1):3 * qx] = 1.0
                    log.info('deconvolve_cube %s: Cleaning inner quarter of each moment plane'
                             % prefix)
                    
                    comp_array[:, pol, :, :], residual_array[:, pol, :, :] = \
                        msmfsclean(dirty_taylor.data[:, pol, :, :], psf_taylor.data[:, pol, :, :],
                                   window_taylor[0, pol, :, :], gain, thresh, niter, scales, fracthresh,
                                   findpeak, prefix)
            else:
                log.info("deconvolve_cube %s: Skipping pol %d" % (prefix, pol))
        
        comp_image = create_image_from_array(comp_array, dirty_taylor.wcs, dirty.polarisation_frame)
        residual_image = create_image_from_array(residual_array, dirty_taylor.wcs, dirty.polarisation_frame)
        
        return_moments = get_parameter(kwargs, "return_moments", False)
        if not return_moments:
            log.info("deconvolve_cube %s: calculating spectral cubes" % prefix)
            comp_image = calculate_image_from_frequency_moments(dirty, comp_image)
            residual_image = calculate_image_from_frequency_moments(dirty, residual_image)
        else:
            log.info("deconvolve_cube %s: constructed moment cubes" % prefix)
    
    elif algorithm == 'hogbom':
        log.info("deconvolve_cube %s: Hogbom clean of each polarisation and channel separately"
                 % prefix)
        gain = get_parameter(kwargs, 'gain', 0.7)
        assert 0.0 < gain < 2.0, "Loop gain must be between 0 and 2"
        thresh = get_parameter(kwargs, 'threshold', 0.0)
        assert thresh >= 0.0
        niter = get_parameter(kwargs, 'niter', 100)
        assert niter > 0
        fracthresh = get_parameter(kwargs, 'fractional_threshold', 0.1)
        assert 0.0 < fracthresh < 1.0
        
        comp_array = numpy.zeros(dirty.data.shape)
        residual_array = numpy.zeros(dirty.data.shape)
        for channel in range(dirty.data.shape[0]):
            for pol in range(dirty.data.shape[1]):
                if psf.data[channel, pol, :, :].max():
                    log.info("deconvolve_cube %s: Processing pol %d, channel %d" % (prefix, pol, channel))
                    if window is None:
                        comp_array[channel, pol, :, :], residual_array[channel, pol, :, :] = \
                            hogbom(dirty.data[channel, pol, :, :], psf.data[channel, pol, :, :],
                                   None, gain, thresh, niter, fracthresh, prefix)
                    else:
                        comp_array[channel, pol, :, :], residual_array[channel, pol, :, :] = \
                            hogbom(dirty.data[channel, pol, :, :], psf.data[channel, pol, :, :],
                                   window[channel, pol, :, :], gain, thresh, niter, fracthresh, prefix)
                else:
                    log.info("deconvolve_cube %s: Skipping pol %d, channel %d" % (prefix, pol, channel))
        
        comp_image = create_image_from_array(comp_array, dirty.wcs, dirty.polarisation_frame)
        residual_image = create_image_from_array(residual_array, dirty.wcs, dirty.polarisation_frame)
    else:
        raise ValueError('deconvolve_cube %s: Unknown algorithm %s' % (prefix, algorithm))
    
    return comp_image, residual_image


def restore_cube(model: Image, psf: Image, residual=None, **kwargs) -> Image:
    """ Restore the model image to the residuals

    :params psf: Input PSF
    :return: restored image

    """
    from scipy.optimize import minpack
    assert isinstance(model, Image), model
    assert isinstance(psf, Image), psf
    assert residual is None or isinstance(residual, Image), residual
    
    restored = copy_image(model)
    
    npixel = psf.data.shape[3]
    sl = slice(npixel // 2 - 7, npixel // 2 + 8)
    
    size = get_parameter(kwargs, "psfwidth", None)
    
    if size is None:
        # isotropic at the moment!
        try:
            fit = fit_2dgaussian(psf.data[0, 0, sl, sl])
            if fit.x_stddev <= 0.0 or fit.y_stddev <= 0.0:
                log.debug('restore_cube: error in fitting to psf, using 1 pixel stddev')
                size = 1.0
            else:
                size = max(fit.x_stddev, fit.y_stddev)
                log.debug('restore_cube: psfwidth = %s' % (size))
        except minpack.error as err:
            log.debug('restore_cube: minpack error, using 1 pixel stddev')
            size = 1.0
        except ValueError as err:
            log.debug('restore_cube: warning in fit to psf, using 1 pixel stddev')
            size = 1.0
    else:
        log.debug('restore_cube: Using specified psfwidth = %s' % (size))
    
    # By convention, we normalise the peak not the integral so this is the volume of the Gaussian
    norm = 2.0 * numpy.pi * size ** 2
    gk = Gaussian2DKernel(size)
    for chan in range(model.shape[0]):
        for pol in range(model.shape[1]):
            restored.data[chan, pol, :, :] = norm * convolve(model.data[chan, pol, :, :], gk, normalize_kernel=False)
    if residual is not None:
        restored.data += residual.data
    return restored
