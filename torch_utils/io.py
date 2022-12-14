from torchaudio.functional import resample
from pathimport import set_module_root
from typing import Tuple, Union
from pathlib import Path
from torch import Tensor
import soundfile as sf
import numpy as np
import torchaudio

set_module_root(".")
from torch_utils.common import get_device, to_numpy

# export list
__all__ = [
    "load_audio",
    "save_audio",
]


def load_audio(
    file_path: Path,
    sample_rate: int = None,
    tensor: bool = False,
) -> Tuple[Union[np.ndarray, Tensor], int]:
    """
    Loads an audio file.

    Parameters
    ----------
    file_path : Path
        Path to the audio file
    sample_rate : int, optional
        Target sample rate, by default None
    tensor : bool, optional
        If True loads a torch Tensor, by default False

    Returns
    -------
    Tuple[np.ndarray, int]
        audio, sample_rate
    """
    if not tensor:
        data, old_sample_rate = sf.read(file_path)
        data = data.T
        if len(data.shape) == 1:
            data = data[None, :]
        if (sample_rate is not None) and (old_sample_rate != sample_rate):
            data = to_numpy(resample(Tensor(data), old_sample_rate, sample_rate))
    else:
        data, old_sample_rate = torchaudio.load(file_path)
        data = data.to(get_device())
        if sample_rate is None:
            sample_rate = old_sample_rate
        elif old_sample_rate != sample_rate:
            data = resample(data, old_sample_rate, sample_rate)

    return data, sample_rate


def save_audio(file_path: Path, data: Union[np.ndarray, Tensor], sample_rate: int):
    """
    Saves an audio file

    Parameters
    ----------
    file_path : Path
        Path to the audio file
    data : Union[np.ndarray, Tensor]
        Audio file to save
    sample_rate : int, optional
        Target sample rate, by default None
    """
    dtype = type(data)

    if dtype == np.ndarray:
        sf.write(file_path, data.T, samplerate=sample_rate)
    elif dtype == Tensor:
        data = data.to("cpu")
        torchaudio.save(file_path, data, sample_rate=sample_rate)
    else:
        err_msg = f"{dtype} is not supported by save_audio"
        raise NotImplementedError(err_msg)
