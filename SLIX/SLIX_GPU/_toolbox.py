from numba import cuda

# DEFAULT PARAMETERS
BACKGROUND_COLOR = -1
MAX_DISTANCE_FOR_CENTROID_ESTIMATION = 3

NUMBER_OF_SAMPLES = 100
TARGET_PEAK_HEIGHT = 0.94
TARGET_PROMINENCE = 0.08


@cuda.jit('void(int8[:, :, :], int8[:, :, :])')
def _peak_cleanup(peaks, resulting_peaks):
    idx, idy = cuda.grid(2)
    sub_peak_array = peaks[idx, idy]

    pos = 0
    while pos < len(sub_peak_array):
        if sub_peak_array[pos] == 1:
            sub_peak_array[pos] = 0
            offset = 1
            while sub_peak_array[(pos + offset) % len(sub_peak_array)] == 1:
                resulting_peaks[idx, idy, (pos + offset) % len(sub_peak_array)] = 0
                sub_peak_array[(pos + offset) % len(sub_peak_array)] = 0
                offset = offset + 1
            resulting_peaks[idx, idy, (pos + (offset-1) // 2) % len(sub_peak_array)] = 1
            pos = pos + offset
        else:
            resulting_peaks[idx, idy, pos] = 0
            pos = pos + 1


@cuda.jit('void(float32[:, :, :], int8[:, :, :], float32[:, :, :])')
def _prominence(image, peak_image, result_image):
    idx, idy = cuda.grid(2)
    sub_image = image[idx, idy]
    sub_peak_array = peak_image[idx, idy]

    for pos in range(len(sub_peak_array)):
        if sub_peak_array[pos] == 1:
            i_min = -len(sub_peak_array) / 2
            i_max = int(len(sub_peak_array) * 1.5)

            i = pos
            left_min = sub_image[pos]
            wlen = len(sub_peak_array) - 1
            while i_min <= i and sub_image[i] <= sub_image[pos] and wlen > 0:
                if sub_image[i] < left_min:
                    left_min = sub_image[i]
                i -= 1
                wlen -= 1

            i = pos
            right_min = sub_image[pos]
            wlen = len(sub_peak_array) - 1
            while i <= i_max and sub_image[i % len(sub_peak_array)] <= sub_image[pos] and wlen > 0:
                if sub_image[i % len(sub_peak_array)] < right_min:
                    right_min = sub_image[i % len(sub_peak_array)]
                i += 1
                wlen -= 1

            result_image[idx, idy, pos] = sub_image[pos] - max(left_min, right_min)
        else:
            result_image[idx, idy, pos] = 0


@cuda.jit('void(float32[:, :, :], int8[:, :, :], float32[:, :, :], float32[:, :, :], float32)')
def _peakwidth(image, peak_image, prominence, result_image, target_height):
    idx, idy = cuda.grid(2)
    sub_image = image[idx, idy]
    sub_peak_array = peak_image[idx, idy]
    sub_prominece = prominence[idx, idy]

    for pos in range(len(sub_peak_array)):
        if sub_peak_array[pos] == 1:
            height = sub_image[pos] - sub_prominece[pos] * target_height
            i_min = -len(sub_peak_array) / 2
            i_max = int(len(sub_peak_array) * 1.5)

            i = int(pos)
            while i_min < i and height < sub_image[i]:
                i -= 1
            left_ip = float(i)
            if sub_image[i] < height:
                # Interpolate if true intersection height is between samples
                left_ip += (height - sub_image[i]) / (sub_image[i + 1] - sub_image[i])

            # Find intersection point on right side
            i = int(pos)
            while i < i_max and height < sub_image[i]:
                i += 1
            right_ip = float(i)
            if sub_image[i] < height:
                # Interpolate if true intersection height is between samples
                right_ip -= (height - sub_image[i]) / (sub_image[i - 1] - sub_image[i])

            result_image[idx, idy, pos] = right_ip - left_ip
        else:
            result_image[idx, idy, pos] = 0


@cuda.jit('void(int8[:, :, :], float32[:, :, :], int8[:, :], float32[:, :, :])')
def _peakdistance(peak_image, centroid_array, number_of_peaks, result_image):
    idx, idy = cuda.grid(2)
    sub_peak_array = peak_image[idx, idy]
    sub_centroid_array = centroid_array[idx, idy]
    current_pair = 0

    current_number_of_peaks = number_of_peaks[idx, idy]

    for i in range(len(sub_peak_array)):
        if sub_peak_array[i] == 1:
            if current_number_of_peaks == 1:
                result_image[idx, idy, i] = 360.0
                break
            elif current_number_of_peaks % 2 == 0:
                left = (i + sub_centroid_array[i]) * 360.0 / len(sub_peak_array)
                right_side_peak = current_number_of_peaks//2
                current_position = i
                while right_side_peak > 0 and current_position < len(sub_peak_array):
                    current_position = current_position + 1
                    if sub_peak_array[current_position] == 1:
                        right_side_peak = right_side_peak - 1
                if right_side_peak > 0:
                    result_image[idx, idy, i] = 0
                else:
                    right = (current_position + sub_centroid_array[current_position]) * 360.0 / len(sub_peak_array)
                    result_image[idx, idy, i] = right - left
                    result_image[idx, idy, current_position] = 360 - (right - left)

                current_pair += 1

            if current_pair == current_number_of_peaks//2:
                break


@cuda.jit('void(int8[:, :, :], float32[:, :, :], int8[:, :], float32[:, :, :])')
def _direction(peak_array, centroid_array, number_of_peaks, result_image):
    idx, idy = cuda.grid(2)
    sub_peak_array = peak_array[idx, idy]
    sub_centroid_array = centroid_array[idx, idy]
    num_directions = result_image.shape[-1]

    current_direction = 0
    current_number_of_peaks = number_of_peaks[idx, idy]

    result_image[idx, idy, :] = BACKGROUND_COLOR
    if current_number_of_peaks // 2 <= num_directions:
        for i in range(len(sub_peak_array)):
            if sub_peak_array[i] == 1:
                left = (i + sub_centroid_array[i]) * 360.0 / len(sub_peak_array)
                if current_number_of_peaks == 1:
                    result_image[idx, idy, current_direction] = (270.0 - left) % 180
                    break
                elif current_number_of_peaks % 2 == 0:
                    right_side_peak = current_number_of_peaks//2
                    current_position = i
                    while right_side_peak > 0 and current_position < len(sub_peak_array):
                        current_position = current_position + 1
                        if sub_peak_array[current_position] == 1:
                            right_side_peak = right_side_peak - 1
                    if right_side_peak == 0:
                        right = (current_position + sub_centroid_array[current_position]) * 360.0 / len(sub_peak_array)
                        if current_number_of_peaks == 2 or abs(180 - (right - left)) < 35:
                            result_image[idx, idy, current_direction] = (270.0 - ((left + right) / 2.0)) % 180
                    current_direction += 1

                    if current_direction == current_number_of_peaks // 2:
                        break


@cuda.jit('void(float32[:, :, :], uint8[:, :, :], uint8[:, :, :], uint8[:, :, :], uint8[:, :, :])')
def _centroid_correction_bases(image, peak_image, reverse_peaks, left_bases, right_bases):
    idx, idy = cuda.grid(2)
    sub_image = image[idx, idy]
    sub_peaks = peak_image[idx, idy]
    sub_reverse_peaks = reverse_peaks[idx, idy]

    max_pos = 0
    for pos in range(len(sub_image)):
        if sub_image[pos] > max_pos:
            max_pos = sub_image[pos]

    for pos in range(len(sub_peaks)):
        if sub_peaks[pos] == 1:

            target_peak_height = max(0, sub_image[pos] - max_pos * (1 - TARGET_PEAK_HEIGHT))
            left_position = MAX_DISTANCE_FOR_CENTROID_ESTIMATION
            right_position = MAX_DISTANCE_FOR_CENTROID_ESTIMATION

            # Check for minima in range
            for offset in range(1, MAX_DISTANCE_FOR_CENTROID_ESTIMATION):
                if sub_reverse_peaks[pos - offset] == 1:
                    left_position = offset
                if sub_reverse_peaks[(pos + offset) % len(sub_reverse_peaks)] == 1:
                    right_position = offset

            # Check for peak height
            for offset in range(abs(left_position)):
                if sub_image[pos - offset] < target_peak_height:
                    left_position = offset
                    break
            for offset in range(right_position):
                if sub_image[(pos + offset) % len(sub_image)] < target_peak_height:
                    right_position = offset
                    break

            left_bases[idx, idy, pos] = left_position
            right_bases[idx, idy, pos] = right_position
        else:
            left_bases[idx, idy, pos] = 0
            right_bases[idx, idy, pos] = 0


@cuda.jit('void(float32[:, :, :], uint8[:, :, :], int8[:, :, :], int8[:, :, :], float32[:, :, :])')
def _centroid(image, peak_image, left_bases, right_bases, centroid_peaks):
    idx, idy = cuda.grid(2)
    sub_image = image[idx, idy]
    sub_peaks = peak_image[idx, idy]
    sub_left_bases = left_bases[idx, idy]
    sub_right_bases = right_bases[idx, idy]

    for pos in range(len(sub_peaks)):
        if sub_peaks[pos] == 1:
            centroid_sum_top = 0.0
            centroid_sum_bottom = 0.0
            for x in range(-sub_left_bases[pos], sub_right_bases[pos]):
                img_pixel = sub_image[(pos + x) % len(sub_image)]
                next_img_pixel = sub_image[(pos + x + 1) % len(sub_image)]
                for interp in range(NUMBER_OF_SAMPLES+1):
                    step = interp / NUMBER_OF_SAMPLES
                    func_val = img_pixel + (next_img_pixel - img_pixel) * step
                    if func_val > sub_peaks[pos] * TARGET_PEAK_HEIGHT:
                        centroid_sum_top += (x + step) * func_val
                        centroid_sum_bottom += func_val

            centroid = centroid_sum_top / centroid_sum_bottom
            if centroid > 1:
                centroid = 1
            if centroid < -1:
                centroid = -1
            centroid_peaks[idx, idy, pos] = centroid
        else:
            centroid_peaks[idx, idy, pos] = 0