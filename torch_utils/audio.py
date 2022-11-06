from pathimport import set_module_root
import torch.nn.functional as F
from random import randrange
from typing import Union
from torch import Tensor
import numpy as np
import torch

set_module_root(".", prefix=True)
from torch_utils.common import get_device, get_np_or_torch, to_numpy


# export list
__all__ = [
    "stft",
    "istft",
    "db",
    "invert_db",
    "power",
    "energy",
    "rms",
    "snr",
    "fade_sides",
    "trim",
]


def stft(
    x: Union[np.ndarray, Tensor],
    sample_rate: int = 16000,
    framesize_ms: int = 10,
    window="hann_window",
    window_overlap=0.5,
    frame_oversampling=4,
) -> Union[np.ndarray, Tensor]:
    """
    Calculates the STFT of a signal.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal of shape (..., T)
    sample_rate : int, optional
        Sample rate of the signal, by default 16000
    framesize_ms : int, optional
        STFT framesize in ms, by default 10
    window : str, optional
        Torch window to use, by default "hann_window"
    window_overlap : float, optional
        Window overlap factor between frames, by default 0.5
    frame_oversampling : int, optional
        Lef zero padding applied for each frame (1 equals to no zero pad), by default 4

    Returns
    -------
    Union[np.ndarray, Tensor]
        STFT of the input of shape (..., T', F')

    Raises
    ------
    AttributeError
        If the window chosen does not exist
    """
    return _stft_istft_core(
        x, True, sample_rate, framesize_ms, window, window_overlap, frame_oversampling
    )


def istft(
    x: Union[np.ndarray, Tensor],
    sample_rate: int = 16000,
    framesize_ms: int = 10,
    window="hann_window",
    window_overlap=0.5,
    frame_oversampling=4,
) -> Union[np.ndarray, Tensor]:
    """
    Calculates the ISTFT of a signal.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal of shape (..., T, F)
    sample_rate : int, optional
        Sample rate of the signal, by default 16000
    framesize_ms : int, optional
        STFT framesize in ms, by default 10
    window : str, optional
        Torch window to use, by default "hann_window"
    window_overlap : float, optional
        Window overlap factor between frames, by default 0.5
    frame_oversampling : int, optional
        Lef zero padding applied for each frame (1 equals to no zero pad), by default 4

    Returns
    -------
    Union[np.ndarray, Tensor]
        ISTFT of the input of shape (..., T')

    Raises
    ------
    AttributeError
        If the window chosen does not exist
    """
    return _stft_istft_core(
        x, False, sample_rate, framesize_ms, window, window_overlap, frame_oversampling
    )


def _stft_istft_core(
    x: Union[np.ndarray, Tensor],
    is_stft: bool,
    sample_rate: int = 16000,
    framesize_ms: int = 10,
    window="hann_window",
    window_overlap=0.5,
    frame_oversampling=2,
) -> Union[np.ndarray, Tensor]:
    """
    Calculates the STFT/ISTFT of a signal.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal
    sample_rate : int, optional
        Sample rate of the signal, by default 16000
    framesize_ms : int, optional
        STFT framesize in ms, by default 10
    window : str, optional
        Torch window to use, by default "hann_window"
    window_overlap : float, optional
        Window overlap factor between frames, by default 0.5
    frame_oversampling : int, optional
        Lef zero padding applied for each frame (1 equals to no zero pad), by default 4

    Returns
    -------
    Union[np.ndarray, Tensor]
        STFT of the input

    Raises
    ------
    AttributeError
        If the window chosen does not exist
    """
    # converting to Tensor
    in_type = type(x)
    if in_type == np.ndarray:
        x = torch.from_numpy(x).to(get_device())

    # getting the window function
    try:
        win_fun = getattr(torch, window)
    except AttributeError:
        allowed_win = [
            "hann_window",
            "hamming_window",
            "bartlett_window",
            "blackman_window",
            "kaiser_window",
        ]
        err_msg = "choose a window between:\n" + ", ".join(allowed_win)
        raise AttributeError(err_msg)

    # parameters of the STFT
    win_length = int(sample_rate * framesize_ms / 1000)
    hop_size = int(win_length * window_overlap)
    n_fft = int(win_length * frame_oversampling)
    _window = torch.zeros(n_fft).to(get_device())
    _window[:win_length] = win_fun(win_length)

    # STFT/ISTFT dependent code
    _transpose = lambda x: x.transpose(-1, -2)
    if is_stft:
        transform = torch.stft
        # compensating for oversampling
        padding = n_fft - win_length
        x = F.pad(x, (0, padding))
    else:
        transform = torch.istft
        x = _transpose(x)
        # fix for torch NOLA check
        eps = 1e-5
        _window[_window < eps] = eps

    y = transform(
        x,
        n_fft=n_fft,
        hop_length=hop_size,
        window=_window,
        return_complex=is_stft,
        center=False,
    )

    # reshaping
    if is_stft:
        y = _transpose(y)

    if in_type == np.ndarray:
        # converting to numpy
        y = to_numpy(y)

    return y


def db(x: Union[np.ndarray, Tensor]) -> Union[np.ndarray, Tensor]:
    """
    Converts linear to dB

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal amplitude

    Returns
    -------
    float
        Input in dB
    """
    eps = 1e-12
    module = get_np_or_torch(x)
    return 20 * module.log10(x + eps)


def invert_db(x: Union[np.ndarray, Tensor]) -> Union[np.ndarray, Tensor]:
    """
    Converts dB to linear

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal amplitude in dB

    Returns
    -------
    float
        Input inverting dB
    """
    return 10 ** (x / 20)


def power(x: Union[np.ndarray, Tensor]) -> float:
    """
    Power of a signal, calculated for each channel.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal

    Returns
    -------
    float
        Power of the signal
    """
    module = get_np_or_torch(x)
    _power = module.einsum("...t,...t->...", x, x.conj())
    _power = module.einsum("...t,...t->...", x, x.conj())
    return _power


def energy(x: Union[np.ndarray, Tensor]) -> float:
    """
    Energy of a signal, calculated for each channel.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal

    Returns
    -------
    float
        Energy of the signal
    """
    samples = x.shape[-1]
    return power(x) / samples


def rms(x: Union[np.ndarray, Tensor]) -> float:
    """
    RMS of a signal, calculated for each channel.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal

    Returns
    -------
    float
        RMS of the signal
    """
    module = get_np_or_torch(x)
    return module.sqrt(energy(x))


def snr(x: Union[np.ndarray, Tensor], noise: Union[np.ndarray, Tensor]) -> float:
    """
    Signal to Noise Ratio (SNR) ratio in dB,
    calculated considering the RMS.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Signal of interest
    noise : Union[np.ndarray, Tensor]
        Interference

    Returns
    -------
    float
        SNR in db
    """
    err_msg0 = "snr supports only 1D and 2D signals"
    assert len(x.shape) in [1, 2], err_msg0
    assert len(noise.shape) in [1, 2], err_msg0
    err_msg1 = "x and noise should be of the same type"
    assert type(x) == type(noise), err_msg1

    module = get_np_or_torch(x)
    channel_mean = lambda x: module.mean(x, -2) if len(x.shape) == 1 else x
    a = channel_mean(db(rms(x)))
    b = channel_mean(db(rms(noise)))
    snr = a - b
    return snr


def _win_to_sides(
    x: Union[np.ndarray, Tensor],
    win: Union[np.ndarray, Tensor],
    fade_len: int,
) -> Union[np.ndarray, Tensor]:
    """
    Handler used to apply a window over the sides of
    a signal.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input of shape [..., C, T]
    win : Union[np.ndarray, Tensor]
        Window
    fade_len : Union[np.ndarray, Tensor]
        Length of each fade in samples

    Returns
    -------
    Union[np.ndarray, Tensor]
        Faded output
    """
    x[..., :fade_len] *= win[:fade_len]
    x[..., -fade_len:] *= win[-fade_len:]
    return x


def fade_sides(x: Union[np.ndarray, Tensor], fade_len: int = 100) -> Union[np.ndarray, Tensor]:
    """
    Apply an half of an Hanning window to both
    sides of the input, in order to obtain a fade in/out.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input of shape [..., C, T]
    fade_len : int, optional
        Length of the fade in samples, by default 10.
        The length of the window is 2 * fade_len + 1.

    Returns
    -------
    Union[np.ndarray, Tensor]
        Faded output
    """
    module = get_np_or_torch(x)
    win = module.hanning(2 * fade_len + 1)
    if module == np:
        y = x.copy()
    else:
        win = win.to(get_device())
        win[-1] = 0
        y = x.detach().clone().to(get_device())
    y = _win_to_sides(y, win, fade_len)

    return y


def trim(
    x: Union[np.ndarray, Tensor],
    sample_rate: int,
    duration: float = 3,
) -> Union[np.ndarray, Tensor]:
    """
    Extracts a random temporal selection from the input.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input of shape [..., T]
    sample_rate : int
        Sample rate in Hz
    duration : float, optional
        Duration of the selection, by default 3 s

    Returns
    -------
    Union[np.ndarray, Tensor]
        Random temporal selection of the input
    """
    module = get_np_or_torch(x)
    x_len = x.shape[-1]
    duration_samples = int(duration * sample_rate)
    selection_start_max = x_len - duration_samples

    if selection_start_max <= 0:
        # if the input is longer than the selection
        # just zero pad the input
        y = module.zeros((*x.shape[:-1], duration_samples))
        y[..., :x_len] = x
    else:
        # applying selection
        start = randrange(0, selection_start_max)
        end = start + duration_samples
        y = x[..., start:end]
    return y
