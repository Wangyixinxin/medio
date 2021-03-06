from pathlib import Path

import pydicom
import numpy as np
from dicom_numpy import combine_slices

from medio.backends.pdcm_unpack_ds import unpack_dataset
from medio.metadata.metadata import MetaData
from medio.metadata.pdcm_ds import convert_ds, MultiFrameFileDataset


class PdcmIO:
    coord_sys = 'itk'
    DEFAULT_CHANNELS_AXIS = 0  # in the transposed image

    @staticmethod
    def read_img(input_path, header=False, channels_axis=None, globber='*', allow_default_affine=False):
        """
        Read a dicom file or folder (series) and return the numpy array and the corresponding metadata
        :param input_path: path-like object (str or pathlib.Path) of the file or directory to read
        :param globber: relevant for a directory - globber for selecting the series files (all files by default)
        :param header: whether to include a header attribute with additional metadata in the returned metadata (single
        file only)
        :param channels_axis: if not None and the image is channeled (e.g. RGB) move the channels to channels_axis in
        the returned image array
        :param allow_default_affine: whether to allow default affine when some tags are missing (multiframe file only)
        :return: numpy array and metadata
        """
        input_path = Path(input_path)
        if input_path.is_dir():
            return PdcmIO.read_dcm_dir(input_path, globber, channels_axis=channels_axis)
        else:
            return PdcmIO.read_dcm_file(input_path, header, allow_default_affine=allow_default_affine,
                                        channels_axis=channels_axis)

    @staticmethod
    def read_dcm_file(filename, header=False, allow_default_affine=False, channels_axis=None):
        """Read a single dicom file"""
        ds = pydicom.dcmread(filename)
        ds = convert_ds(ds)
        if ds.__class__ is MultiFrameFileDataset:
            img, affine = unpack_dataset(ds, allow_default_affine=allow_default_affine)
        else:
            img, affine = combine_slices([ds])
        metadata = PdcmIO.aff2meta(affine)
        if header:
            metadata.header = {str(key): ds[key] for key in ds.keys()}
        img = PdcmIO.move_channels_axis(img, samples_per_pixel=ds.SamplesPerPixel, channels_axis=channels_axis)
        return img, metadata

    @staticmethod
    def read_dcm_dir(input_dir, globber='*', channels_axis=None):
        """Reads a 3D dicom image: input path can be a file or directory (DICOM series)"""
        # find all dicom files within the specified folder, read every file separately and sort them by InstanceNumber
        files = list(Path(input_dir).glob(globber))
        if len(files) == 0:
            raise FileNotFoundError(f'Received an empty directory: "{input_dir}"')
        slices = [pydicom.dcmread(filename) for filename in files]
        slices.sort(key=lambda ds: ds.get('InstanceNumber', 0))
        img, affine = combine_slices(slices)
        metadata = PdcmIO.aff2meta(affine)
        img = PdcmIO.move_channels_axis(img, samples_per_pixel=slices[0].SamplesPerPixel, channels_axis=channels_axis)
        return img, metadata

    @staticmethod
    def aff2meta(affine):
        return MetaData(affine, coord_sys=PdcmIO.coord_sys)

    @staticmethod
    def move_channels_axis(array, samples_per_pixel, source=DEFAULT_CHANNELS_AXIS, channels_axis=None):
        # TODO: the following assert is not always True, depends on Planar Configuration (0028,0006)
        # assert array.shape[source] == samples_per_pixel
        if (samples_per_pixel > 1) and (channels_axis is not None):
            return np.moveaxis(array, source, channels_axis)
        return array

    @staticmethod
    def save_arr2dcm_file(output_filename, template_filename, img_arr, dtype=None, keep_rescale=False):
        """
        Writes a dicom single file image using template file, without the intensity transformation from template dataset
        unless keep_rescale is True
        :param output_filename: path-like object of the output file to be saved
        :param template_filename: the single dicom scan whose metadata is used
        :param img_arr: numpy array of the image to be saved, should be in the same orientation as template_filename
        :param dtype: the dtype for the numpy array, for example 'int16'. If None - will use the dtype of the template
        :param keep_rescale: whether to keep intensity rescale values
        """
        ds = pydicom.dcmread(template_filename)
        ds = convert_ds(ds)
        if not keep_rescale:
            if isinstance(ds, MultiFrameFileDataset):
                ds.del_intensity_trans()
            else:
                del ds.RescaleSlope
                del ds.RescaleIntercept
        if dtype is None:
            img_arr = img_arr.astype(ds.pixel_array.dtype, copy=False)
        else:
            img_arr = img_arr.astype(dtype, copy=False)
        ds.PixelData = img_arr.tobytes()
        ds.save_as(output_filename)
