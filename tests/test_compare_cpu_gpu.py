import SLIX
import numpy

from matplotlib import pyplot as plt
import tifffile


class TestToolbox:
    def setup_method(self, method):
        self.example = SLIX.toolbox.read_image('tests/files/demo.nii')

    def test_compare_peaks(self):
        gpu_peaks = SLIX.toolbox.gpu_toolbox.peaks(self.example)
        cpu_peaks = SLIX.toolbox.cpu_toolbox.peaks(self.example)

        assert numpy.all(cpu_peaks == gpu_peaks)

    def test_compare_num_peaks(self):
        gpu_peaks = SLIX.toolbox.gpu_toolbox.num_peaks(self.example)
        cpu_peaks = SLIX.toolbox.cpu_toolbox.num_peaks(self.example)

        assert numpy.all(cpu_peaks == gpu_peaks)

    def test_compare_prominence(self):
        gpu_prominence = SLIX.toolbox.gpu_toolbox.peak_prominence(self.example)
        cpu_prominence = SLIX.toolbox.cpu_toolbox.peak_prominence(self.example)

        assert numpy.all(numpy.isclose(cpu_prominence, gpu_prominence))

    def test_compare_mean_prominence(self):
        gpu_prominence = SLIX.toolbox.gpu_toolbox.mean_peak_prominence(self.example)
        cpu_prominence = SLIX.toolbox.cpu_toolbox.mean_peak_prominence(self.example)

        assert numpy.all(numpy.isclose(cpu_prominence, gpu_prominence))

    def test_compare_peakwidth(self):
        gpu_peakwidth = SLIX.toolbox.gpu_toolbox.peak_width(self.example)
        cpu_peakwidth = SLIX.toolbox.cpu_toolbox.peak_width(self.example)

        assert numpy.all(numpy.isclose(cpu_peakwidth, gpu_peakwidth))

    def test_compare_mean_peakwidth(self):
        gpu_peakwidth = SLIX.toolbox.gpu_toolbox.mean_peak_width(self.example)
        cpu_peakwidth = SLIX.toolbox.cpu_toolbox.mean_peak_width(self.example)

        assert numpy.all(numpy.isclose(gpu_peakwidth, cpu_peakwidth))

    def test_compare_peakdistance(self):
        gpu_peaks = SLIX.toolbox.gpu_toolbox.peaks(self.example, return_numpy=False)
        cpu_peaks = SLIX.toolbox.cpu_toolbox.peaks(self.example)
        gpu_centroids = SLIX.toolbox.gpu_toolbox.centroid_correction(self.example, gpu_peaks, return_numpy=False)
        cpu_centroids = SLIX.toolbox.cpu_toolbox.centroid_correction(self.example, cpu_peaks)

        gpu_distance = SLIX.toolbox.gpu_toolbox.peak_distance(gpu_peaks, gpu_centroids)
        cpu_distance = SLIX.toolbox.cpu_toolbox.peak_distance(cpu_peaks, cpu_centroids)

        assert numpy.all(numpy.isclose(cpu_distance, gpu_distance))

    def test_compare_centroids(self):
        gpu_peaks = SLIX.toolbox.gpu_toolbox.peaks(self.example, return_numpy=False)
        cpu_peaks = SLIX.toolbox.cpu_toolbox.peaks(self.example)
        gpu_centroids = SLIX.toolbox.gpu_toolbox.centroid_correction(self.example, gpu_peaks)
        cpu_centroids = SLIX.toolbox.cpu_toolbox.centroid_correction(self.example, cpu_peaks)

        print(gpu_centroids.shape)
        tifffile.imwrite('/tmp/gpu.tiff', numpy.moveaxis(gpu_centroids, -1, 0))
        tifffile.imwrite('/tmp/cpu.tiff', numpy.moveaxis(cpu_centroids, -1, 0))

        assert numpy.all(numpy.isclose(cpu_centroids, gpu_centroids))

    def test_compare_direction(self):
        gpu_peaks = SLIX.toolbox.gpu_toolbox.peaks(self.example, return_numpy=False)
        cpu_peaks = SLIX.toolbox.cpu_toolbox.peaks(self.example)
        gpu_centroids = SLIX.toolbox.gpu_toolbox.centroid_correction(self.example, gpu_peaks, return_numpy=False)
        cpu_centroids = SLIX.toolbox.cpu_toolbox.centroid_correction(self.example, cpu_peaks)

        gpu_direction = SLIX.toolbox.gpu_toolbox.direction(gpu_peaks, gpu_centroids)
        cpu_direction = SLIX.toolbox.cpu_toolbox.direction(cpu_peaks, cpu_centroids)

        assert numpy.all(numpy.isclose(cpu_direction, gpu_direction))