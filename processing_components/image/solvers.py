"""
Definition of structures needed by the function interface. These are mostly
subclasses of astropy classes.
"""

import numpy

from data_models.memory_data_models import Visibility, Image
from data_models.parameters import get_parameter

from ..image.deconvolution import deconvolve_cube
from ..visibility.base import copy_visibility
from ..imaging.base import predict_skycomponent_visibility
from ..imaging.imaging_functions import predict_function, invert_function

import logging

log = logging.getLogger(__name__)


def solve_image(vis: Visibility, model: Image, components=None, context='2d', **kwargs) -> \
        (Visibility, Image, Image):
    """Solve for image using deconvolve_cube and specified predict, invert

    This is the same as a majorcycle/minorcycle algorithm. The components are removed prior to deconvolution.
    
    See also arguments for predict, invert, deconvolve_cube functions.2d

    :param vis:
    :param model: Model image
    :param predict: Predict function e.g. predict_2d, predict_wstack
    :param invert: Invert function e.g. invert_2d, invert_wstack
    :return: Visibility, model
    """
    nmajor = get_parameter(kwargs, 'nmajor', 5)
    thresh = get_parameter(kwargs, "threshold", 0.0)
    log.info("solve_image: Performing %d major cycles" % nmajor)
    
    # The model is added to each major cycle and then the visibilities are
    # calculated from the full model
    vispred = copy_visibility(vis, zero=True)
    visres = copy_visibility(vis, zero=True)

    vispred = predict_function(vispred, model, context=context, **kwargs)
    
    if components is not None:
        vispred = predict_skycomponent_visibility(vispred, components)
    
    visres.data['vis'] = vis.data['vis'] - vispred.data['vis']
    dirty, sumwt = invert_function(visres, model, context=context, dopsf=False, **kwargs)
    assert sumwt.any() > 0.0, "Sum of weights is zero"
    psf, sumwt = invert_function(visres, model, context=context, dopsf=True, **kwargs)
    assert sumwt.any() > 0.0, "Sum of weights is zero"
    
    for i in range(nmajor):
        log.info("solve_image: Start of major cycle %d" % i)
        cc, res = deconvolve_cube(dirty, psf, **kwargs)
        model.data += cc.data
        vispred.data['vis'][...]=0.0
        vispred = predict_function(vispred, model, context=context, **kwargs)
        visres.data['vis'] = vis.data['vis'] - vispred.data['vis']
        dirty, sumwt = invert_function(visres, model, context=context, dopsf=False, **kwargs)
        if numpy.abs(dirty.data).max() < 1.1 * thresh:
            log.info("Reached stopping threshold %.6f Jy" % thresh)
            break
        log.info("solve_image: End of minor cycles")

    log.info("solve_image: End of major cycles")
    return visres, model, dirty
