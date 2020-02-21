import nibabel
import numpy
import multiprocessing
import peakutils
import tifffile
import sys
from read_roi import read_roi_zip
from scipy.signal import peak_widths, savgol_filter, find_peaks

import pymp
from pymp import shared

BACKGROUND_COLOR = -1
CPU_COUNT = multiprocessing.cpu_count()//2

def read_image(FILEPATH):
    """
    Reads iamge file and returns it.
    
    Arguments:
        FILEPATH {str} -- Path to image

    Returns:
        numpy.array -- Image with shape [x, y, z] where [x, y] is the size of a single image and z specifies the number of images
    """
    # Load NIfTI dataset
    if FILEPATH.endswith('.nii'):
        data = nibabel.load(FILEPATH).get_fdata()
        data = numpy.squeeze(numpy.swapaxes(data, 0, 1))
    else:
        data = tifffile.imread(FILEPATH)
        data = numpy.squeeze(numpy.moveaxis(data, 0, -1))

    return data

def create_background_mask(IMAGE, threshold=10):
    """Creates a background mask based on given threshhold. As all background pixels are near zero when looking through the z-axis plot
    this method should remove most of the background allowing better approximations using the available features. It is advised to use this function.
    
    Arguments:
        IMAGE {numpy.array} -- 2D/3D-image containing the z-axis in the last dimension
    
    Keyword Arguments:
        threshold {int} -- Threshhold for mask creation (default: {10})
    
    Returns:
        numpy.array -- 1D/2D-image which masks the background as True and foreground as False
    """
    mask = numpy.all(IMAGE < threshold, axis=-1)
    return mask

def zaxis_from_imagej_roiset(IMAGE, PATH_TO_ROISET, extend=True):
    rois = read_roi_zip(PATH_TO_ROISET)
    x, y, z = IMAGE.shape[0], IMAGE.shape[1], IMAGE.shape[2]
    
    if extend:
        roi_set = pymp.shared.array((len(rois.items()), 2*z), dtype='float32')
    else:
        roi_set = pymp.shared.array((len(rois.items()), z), dtype='float32')

    roi_values = list(dict(rois.items()).values())
    name_set = list(dict(rois.items()).keys())

    with pymp.Parallel(CPU_COUNT) as p:
        for i in p.range(1, len(rois)):
                value = roi_values[i]
                name = value['name']
                width, height = value['width'], value['height']
                roi_type = value['type']
                left, top = value['left'], value['top']
                center = (left + width/2, top + height/2)

                if width == height and roi_type == 'oval':
                    x_indices = numpy.arange(top, top+height+1)
                    y_indices = numpy.arange(left, left+width+1)
                    rectangle_indices = numpy.array(numpy.meshgrid(x_indices, y_indices)).T.reshape(-1, 2)
                    rectangle_indices = rectangle_indices[(rectangle_indices[:, 0] - center[1])**2 + (rectangle_indices[:, 1] - center[0])**2 < width*height]
                    
                    roi = IMAGE[rectangle_indices[:, 0], rectangle_indices[:, 1], :]
                    average_per_dimension = numpy.average(roi, axis=0).flatten()
                    if extend:
                        average_per_dimension = numpy.concatenate((average_per_dimension[-z//2:], average_per_dimension, average_per_dimension[:z//2]))
                    name_set[i] = name
                    roi_set[i] = average_per_dimension
                else:
                    continue

    return roi_set[1:], name_set[1:]

def zaxis_roiset(IMAGE, ROISIZE, extend=True):
    """
    Create z-axis profile of given image by creating a roiset image containing the average value of pixels within the specified ROISIZE. 
    The returned image will have twice the size in the z-axis as the both halfs will be doubled for the peak detection.

    
    Arguments:
        IMAGE {numpy.memmap} -- Image containing multiple images in a z-stack 
        ROISIZE {int} -- Size in pixels which are used to create the region of interest image
    
    Returns:
        numpy.array -- Image with shape [x/ROISIZE, y/ROISIZE, 2*z] containing the average value of the given roiset for each image in z-axis.
    """
    # Get image dimensions
    x = IMAGE.shape[0]
    y = IMAGE.shape[1]
    z = IMAGE.shape[2]
    nx = numpy.ceil(x/ROISIZE).astype('int')
    ny = numpy.ceil(y/ROISIZE).astype('int')
    
    if extend:
        roi_set = pymp.shared.array((nx * ny, 2*z), dtype='float32')
    else:
        roi_set = pymp.shared.array((nx * ny, z), dtype='float32')

    # Roisize == 1 is exactly the same as the original image
    if ROISIZE > 1:
        with pymp.Parallel(CPU_COUNT) as p:
            for i in p.range(0, nx):
                for j in range(0, ny):
                    # Create average of selected ROI and append two halfs to the front and back
                    roi = IMAGE[ROISIZE*i:ROISIZE*i+ROISIZE, ROISIZE*j:ROISIZE*j+ROISIZE, :]
                    average_per_dimension = numpy.average(numpy.average(roi, axis=1), axis=0).flatten()
                    if extend:
                        average_per_dimension = numpy.concatenate((average_per_dimension[-z//2:], average_per_dimension, average_per_dimension[:z//2]))
                    roi_set[i*ny + j] = average_per_dimension
    else:
        with pymp.Parallel(CPU_COUNT) as p:
            for i in p.range(0, nx):
                for j in range(0, ny):
                    # Create average of selected ROI and append two halfs to the front and back
                    roi = IMAGE[i, j, :]
                    if extend:
                        roi = numpy.concatenate((roi[-z//2:], roi, roi[:z//2]))
                    roi_set[i*ny + j] = roi
            
    return roi_set

def reshape_array_to_image(image, x, ROISIZE):
    """
    Convert array back to image keeping the lower resolution based on the ROISIZE.
    
    Arguments:
        image {numpy.array} -- Array created by other methods with lower resolution based on ROISIZE
        x {int} -- Size of original image in x-dimension
        ROISIZE {int} -- Size of the ROI used for evaluating the roiset
    
    Returns:
        numpy.array -- Reshaped image based on the input array
    """
    image_reshaped = image.reshape((numpy.ceil(x/ROISIZE).astype('int'),image.shape[0]//numpy.ceil(x/ROISIZE).astype('int')))
    return image_reshaped

def peak_array_from_roiset(roiset, cut_edges=True):    
    """
    Generate array visualizing the number of peaks present in each pixel of a given roiset.
    
    Arguments:
        roiset {numpy.array} -- Roiset generated with the zaxis_roiset method
    
    Returns:
        numpy.array -- 2D-Array with the amount of peaks in each pixel
    """
    peak_array = pymp.shared.array((roiset.shape[0]), dtype='uint8')
    z = roiset.shape[1]//2

    roiset = (roiset.copy() - roiset.std())/roiset.mean()
    with pymp.Parallel(CPU_COUNT) as p:
        for i in p.range(0, len(roiset)):
            roi = roiset[i]
            # Generate peaks
            #peaks = peakutils.indexes(roi, thres=0.5, min_dist=1/10 * z)
            peaks, _ = find_peaks(roi, width=1, prominence=(0.125, None), distance=numpy.ceil(1.0/72.0 * z))
            # Only consider peaks which are in bounds
            if cut_edges:
                peaks = peaks[(peaks >= z//2) & (peaks <= len(roi)-z//2)]
                # Filter double peak
                if numpy.all(numpy.isin([z//2, len(roi)-z//2], peaks)):
                    peaks = peaks[1:]
                peak_array[i] = len(peaks[(peaks >= z//2) & (peaks <= len(roi)-z//2)])
            else:
                peak_array[i] = len(peaks)
    return peak_array

def peakwidth_array_from_roiset(roiset, cut_edges=True):
    #TODO: Bestimme nicht nur Peaks, sondern auch deren Breite
    #TODO: Setze Breite und Abstand in Verhältnis zu der Inklination (vorerst zwei Bilder?)
    
    peak_array = pymp.shared.array((roiset.shape[0]), dtype='float32')
    z = roiset.shape[1]//2

    roiset = (roiset.copy() - roiset.std())/roiset.mean()
    with pymp.Parallel(CPU_COUNT) as p:
        for i in p.range(0, len(roiset)):
            roi = roiset[i]
            # Generate peaks
            #peaks = peakutils.indexes(filtered_roi, thres=0.5, min_dist=1/10 * z)
            peaks, _ = find_peaks(roi, width=1, prominence=(0.125, None), distance=numpy.ceil(1.0/72.0 * z))
            if cut_edges:
                peaks = peaks[(peaks >= z//2) & (peaks <= len(roi)-z//2)]
                # Filter double peak
                if numpy.all(numpy.isin([z//2, len(roi)-z//2], peaks)):
                    peaks = peaks[1:]
                amount_of_peaks = len(peaks[(peaks >= z//2) & (peaks <= len(roi)-z//2)])
            else:
                amount_of_peaks = len(peaks)
            #peaks = (peaks - z//2) * 360 / z

            if amount_of_peaks > 0:
                widths = peak_widths(roi, peaks, rel_height=0.5)
                peak_array[i] = numpy.mean(widths[0])
            else:
                peak_array[i] = 0

    return peak_array

def non_crossing_direction_array_from_roiset(roiset, cut_edges=True):
    peak_array = pymp.shared.array((roiset.shape[0]), dtype='float32')
    z = roiset.shape[1]//2
    
    roiset = (roiset.copy() - roiset.std())/roiset.mean()
    with pymp.Parallel(CPU_COUNT) as p:
        for i in p.range(0, len(roiset)):
            roi = roiset[i]
            # Generate peaks
            #peaks = peakutils.indexes(roi, thres=0.5, min_dist=1/10 * z)
            peaks, _ = find_peaks(roi, width=1, prominence=(0.125, None), distance=numpy.ceil(1.0/72.0 * z))
            if cut_edges:
                peaks = peaks[(peaks >= z//2) & (peaks <= len(roi)-z//2)]
                # Filter double peak
                if numpy.all(numpy.isin([z//2, len(roi)-z//2], peaks)):
                    peaks = peaks[1:]
                amount_of_peaks = len(peaks[(peaks >= z//2) & (peaks <= len(roi)-z//2)])
            else:
                amount_of_peaks = len(peaks)

            # Scale peaks correctly for direction
            peaks = (peaks - z//2) * (360.0 / z)
            # Change behaviour based on amount of peaks (steep, crossing, ...)
            if amount_of_peaks == 1:
                peak_array[i] = (270 - peaks[0])%180
            elif amount_of_peaks == 2:
                pos = (270 - ((peaks[1]+peaks[0])/2.0))%180
                peak_array[i] = pos
            else:
                peak_array[i] = BACKGROUND_COLOR
    return peak_array

def crossing_direction_array_from_roiset(roiset, cut_edges=True):
    peak_array = pymp.shared.array((roiset.shape[0], 2), dtype='float32')
    z = roiset.shape[1]//2
    
    roiset = (roiset.copy() - roiset.std())/roiset.mean()
    with pymp.Parallel(CPU_COUNT) as p:
        for i in p.range(0, len(roiset)):
            roi = roiset[i]
            # Generate peaks
            #peaks = peakutils.indexes(roi, thres=0.5, min_dist=1/10 * z)
            peaks, _ = find_peaks(roi, width=1, prominence=(0.125, None), distance=numpy.ceil(1.0/72.0 * z))
            if cut_edges:
                peaks = peaks[(peaks >= z//2) & (peaks <= len(roi)-z//2)]
                # Filter double peak
                if numpy.all(numpy.isin([z//2, len(roi)-z//2], peaks)):
                    peaks = peaks[1:]
                amount_of_peaks = len(peaks[(peaks >= z//2) & (peaks <= len(roi)-z//2)])
            else:
                amount_of_peaks = len(peaks)

            # Scale peaks correctly for direction
            peaks = (peaks - z//2) * (360.0 / z)
            # Change behaviour based on amount of peaks (steep, crossing, ...)
            if amount_of_peaks == 1:
                peak_array[i] = (270 - peaks[0])%180
            elif amount_of_peaks == 2:
                pos = (270 - ((peaks[1]+peaks[0])/2.0))%180
                peak_array[i] = pos
            elif amount_of_peaks == 3:
                if(numpy.abs((peaks[0] - peaks[2]) - 180) < 35):
                    peak_array[i, 0] = (270 - ((peaks[2]+peaks[0])/2.0))%180
                    peak_array[i, 1] = (270 - peaks[1])%180
                elif(numpy.abs((peaks[1] - peaks[0]) - 180) < 35):
                    peak_array[i, 0] = (270 - ((peaks[1]+peaks[0])/2.0))%180
                    peak_array[i, 1] = (270 - peaks[2])%180 
                elif(numpy.abs((peaks[1] - peaks[2]) - 180) < 35):
                    peak_array[i, 0] = (270 - ((peaks[1]+peaks[2])/2.0))%180
                    peak_array[i, 1] = (270 - peaks[0])%180
                else:
                    peak_array[i] = BACKGROUND_COLOR 
            elif amount_of_peaks == 4:
                if(numpy.abs((peaks[3] - peaks[1]) - 180) < 35):
                    peak_array[i, 1] = (270 - ((peaks[3]+peaks[1])/2.0))%180
                else:
                    peak_array[i, 1] = BACKGROUND_COLOR
                if(numpy.abs((peaks[2] - peaks[0]) - 180) < 35):
                    peak_array[i, 0] = (270 - ((peaks[2]+peaks[0])/2.0))%180   
                else:
                    peak_array[i] = BACKGROUND_COLOR    
            else:
                peak_array[i] = BACKGROUND_COLOR
    return peak_array

def max_array_from_roiset(roiset):
    #TODO: I'm totally sure that that code can be optimized
    max_array = pymp.shared.array((roiset.shape[0]), dtype='float32')
    with pymp.Parallel(CPU_COUNT) as p:
        for i in p.range(0, len(roiset)):
            roi = roiset[i]
            max_array[i] = numpy.max(roi)
    return max_array

def min_array_from_roiset(roiset):
    #TODO: I'm totally sure that that code can be optimized
    min_array = pymp.shared.array((roiset.shape[0]), dtype='float32')
    with pymp.Parallel(CPU_COUNT) as p:
        for i in p.range(0, len(roiset)):
            roi = roiset[i]
            min_array[i] = numpy.min(roi)
    return min_array

def avg_array_from_roiset(roiset):
    #TODO: I'm totally sure that that code can be optimized
    avg_array = pymp.shared.array((roiset.shape[0]), dtype='float32')
    with pymp.Parallel(CPU_COUNT) as p:
        for i in p.range(0, len(roiset)):
            roi = roiset[i]
            avg_array[i] = numpy.mean(roi)
    return avg_array

def z_scoring_peak_estimation(y, lag=5, threshold=3.5, influence=0.5) -> numpy.ndarray:
    print(y.shape)
    signals = numpy.zeros(len(y))
    filteredY = numpy.array(y)
    avgFilter = numpy.zeros(len(y))
    stdFilter = numpy.zeros(len(y))
    avgFilter[lag - 1] = numpy.mean(y[:lag])
    stdFilter[lag - 1] = numpy.std(y[:lag])

    for i in range(lag, len(y)):
        if abs(y[i] - avgFilter[i-1]) > threshold * stdFilter[i-1]:
            if y[i] > avgFilter[i-1]:
                signals[i] = +1
            else:
                signals[i] = -1
            filteredY[i] = influence * y[i] + (1-influence) * filteredY[i-1]
        else:
            signals[i] = 0
            filteredY[i] = y[i]
        
        avgFilter[i] = numpy.mean(filteredY[(i-lag+1):i+1])
        stdFilter[i] = numpy.std(filteredY[(i-lag+1):i+1])

    return signals