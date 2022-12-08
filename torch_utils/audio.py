from torchaudio.functional import melscale_fbanks
from pathimport import set_module_root
from typing import Optional, Union
import torch.nn.functional as F
from random import randrange
from torch import Tensor
from fnnls import fnnls
import numpy as np
import torch

set_module_root(".", prefix=True)
from torch_utils.common import get_device, get_np_or_torch, to_numpy


# export list
__all__ = [
    "stft",
    "istft",
    "MelFilterbank",
    "MelInverseFilterbank",
    "db",
    "invert_db",
    "power",
    "energy",
    "rms",
    "snr",
    "fade_sides",
    "random_trim",
    "trim_silence",
]


def stft(
    x: Union[np.ndarray, Tensor],
    sample_rate: int = 16000,
    hopsize_ms: int = 10,
    window: str = "hann",
    win_len_ms: int = 20,
    win_oversamp: int = 2,
) -> Union[np.ndarray, Tensor]:
    """
    Calculates the STFT of a signal.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal of shape (..., T)
    sample_rate : int, optional
        Sample rate of the signal, by default 16000
    hopsize_ms : int, optional
        STFT hopsize in ms, by default 10
    window : str, optional
        Torch window to use, by default "hann"
    win_len_ms : int, optional
        Window length in ms, by default 20 ms
    win_oversamp : int, optional
        Zero padding applied equal to the window length
        (1 equals to no zero pad), by default 2

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
        True,
        x,
        sample_rate,
        hopsize_ms,
        window,
        win_len_ms,
        win_oversamp,
    )


def istft(
    x: Union[np.ndarray, Tensor],
    sample_rate: int = 16000,
    hopsize_ms: int = 10,
    window: str = "hann",
    win_len_ms: int = 20,
    win_oversamp: int = 2,
) -> Union[np.ndarray, Tensor]:
    """
    Calculates the ISTFT of a signal.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input signal of shape (..., T, F)
    sample_rate : int, optional
        Sample rate of the signal, by default 16000
    hopsize_ms : int, optional
        STFT hopsize in ms, by default 10
    window : str, optional
        Torch window to use, by default "hann"
    win_len_ms : int, optional
        Window length in ms, by default 20 ms
    win_oversamp : int, optional
        Zero padding applied equal to the window length
        (1 equals to no zero pad), by default 2

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
        False,
        x,
        sample_rate,
        hopsize_ms,
        window,
        win_len_ms,
        win_oversamp,
    )


def _stft_istft_core(
    is_stft: bool,
    x: Union[np.ndarray, Tensor],
    sample_rate: int = 16000,
    hopsize_ms: int = 10,
    window: str = "hann",
    win_len_ms: int = 20,
    win_oversamp: int = 2,
) -> Union[np.ndarray, Tensor]:
    """
    Calculates the STFT/ISTFT of a signal.

    Parameters
    ----------
    is_stft : bool
        Selects between STFT and ISTFT
    x : Union[np.ndarray, Tensor]
        Input signal
    sample_rate : int, optional
        Sample rate of the signal, by default 16000
    hopsize_ms : int, optional
        STFT hopsize in ms, by default 10
    window : str, optional
        Torch window to use, by default "hann"
    win_len_ms : int, optional
        Window length in ms, by default 20 ms
    win_oversamp : int, optional
        Zero padding applied equal to the window length
        (1 equals to no zero pad), by default 2

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
        x = torch.from_numpy(x)

    # getting the window function
    try:
        window += "_window"
        win_fun = getattr(torch, window)
    except AttributeError:
        allowed_win = [w + "_window" for w in ["hann", "hamming", "bartlett", "blackman", "kaiser"]]
        err_msg = "choose a window between:\n" + ", ".join(allowed_win)
        raise AttributeError(err_msg)

    # parameters of the STFT
    _ms_to_samples = lambda x: int(x * sample_rate / 1000)
    win_len = _ms_to_samples(win_len_ms)
    hopsize = _ms_to_samples(hopsize_ms)
    n_fft = int(win_len * win_oversamp)
    _window = torch.zeros(n_fft)
    _window[:win_len] = win_fun(win_len)
    _window = _window.to(x.device)

    # STFT/ISTFT dependent code
    _transpose = lambda x: x.transpose(-1, -2)
    if is_stft:
        transform = torch.stft
        # compensating for oversampling and center==True
        pad_ovr = n_fft - win_len
        pad_ctr = win_len // 2
        x = F.pad(x, (pad_ctr, pad_ovr))
    else:
        transform = torch.istft
        x = _transpose(x)

    y = transform(
        x,
        n_fft=n_fft,
        hop_length=hopsize,
        window=_window,
        return_complex=is_stft,
        center=True,
    )

    if is_stft:
        # reshaping
        y = _transpose(y)
        # compensating for center==True
        y = y[:, 1:]

    if in_type == np.ndarray:
        # converting to numpy
        y = to_numpy(y)

    return y


class MelFilterbank:
    def __init__(
        self,
        sample_rate: int,
        n_freqs: int,
        n_mels: int,
        device: Optional[torch.device] = None,
    ) -> None:
        """
        Apply Mel filterbank to the input batch.

        Parameters
        ----------
        sample_rate : int
            Sample rate of the signal
        n_freqs : int
            Stft frequencies
        n_mels : int
            Number of mel frequencies
        device : Optional[torch.device], optional
            Device for the filterbank matrix, by default None
        """
        self.sample_rate = sample_rate
        self.n_freqs = n_freqs
        self.n_mels = n_mels
        self.device = device or get_device()
        self.filterbank = self._get_filterbank()

    def _get_filterbank(self) -> Tensor:
        """
        Gets the mel filterbank

        Returns
        -------
        Tensor
            Mel filterbank matrix
        """
        filterbank = melscale_fbanks(
            n_freqs=self.n_freqs,
            n_mels=self.n_mels,
            f_min=30,
            f_max=self.sample_rate // 2,
            sample_rate=self.sample_rate,
        )
        filterbank = filterbank.to(self.device)

        return filterbank

    def __call__(self, x: Union[np.ndarray, Tensor]) -> Tensor:
        """
        Parameters
        ----------
        x : Union[np.ndarray, Tensor]
            Signal of shape (B, C, T, n_freq)

        Returns
        -------
        Tensor
            STFT of shape (B, C, T, n_mel)
        """
        is_np = get_np_or_torch(x) == np
        if is_np:
            x = Tensor(x, device=self.device)

        y = x @ self.filterbank

        if is_np:
            y = to_numpy(y)
        return y


class MelInverseFilterbank:
    def __init__(
        self,
        sample_rate: int,
        n_freqs: int,
        n_mels: int,
        device: Optional[torch.device] = None,
    ) -> None:
        """
        Apply inverse Mel filterbank to the input batch,
        to get back a spectrogram.

        Parameters
        ----------
        sample_rate : int
            Sample rate of the signal
        n_freqs : int
            Stft frequencies
        n_mels : int
            Number of mel frequencies
        device : Optional[torch.device], optional
            Device for the filterbank matrix, by default None
        """
        self.sample_rate = sample_rate
        self.n_freqs = n_freqs
        self.n_mels = n_mels
        self.device = device or get_device()
        self.filterbank = self._get_filterbank()

    def _get_filterbank(self) -> Tensor:
        """
        Gets the mel filterbank

        Returns
        -------
        Tensor
            Mel filterbank matrix
        """
        filterbank = melscale_fbanks(
            n_freqs=self.n_freqs,
            n_mels=self.n_mels,
            f_min=30,
            f_max=self.sample_rate // 2,
            sample_rate=self.sample_rate,
        )
        # pseudo-inverse is used to approximate
        # the inverse transform
        filterbank = torch.linalg.pinv(filterbank)
        filterbank = filterbank.to(self.device)

        return filterbank

    def __call__(self, x: Union[np.ndarray, Tensor]) -> Union[np.ndarray, Tensor]:
        """
        Parameters
        ----------
        x : Union[np.ndarray, Tensor]
            Signal of shape (B, C, T, n_freq)

        Returns
        -------
        Union[np.ndarray, Tensor]
            STFT of shape (B, C, T, n_mel)
        """
        is_np = get_np_or_torch(x) == np
        if is_np:
            x = Tensor(x, device=self.device)

        y = x @ self.filterbank

        if is_np:
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
        Input of shape (..., C, T)
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
        Input of shape (..., C, T)
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
        y = x.detach().clone()
    y = _win_to_sides(y, win, fade_len)

    return y


def random_trim(
    x: Union[np.ndarray, Tensor],
    sample_rate: int,
    duration: float = 3,
) -> Union[np.ndarray, Tensor]:
    """
    Extracts a random temporal selection from the input.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input of shape (..., T)
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


def trim_silence(
    x: Union[np.ndarray, Tensor],
    threshold_db: float = -30,
    margin: int = 0,
) -> Union[np.ndarray, Tensor]:
    """
    Trims the silences at the beginning and end of a sample.

    Parameters
    ----------
    x : Union[np.ndarray, Tensor]
        Input sample of shape (T,)
    threshold_db : float, optional
        Relative to x.max() to detect the silences, by default -30 dB
    margin : int, optional
        Samples kept at both sides after the trimming, by default 0

    Returns
    -------
    Union[np.ndarray, Tensor]
        Trimmed ouput of shape (T',)
    """
    module = get_np_or_torch(x)

    # finding the start and end points
    threshold = invert_db(threshold_db)
    threshold *= module.abs(x).max()
    thr = module.zeros_like(x, dtype=int)
    thr[module.abs(x) > threshold] = 1
    thr = thr if module == np else thr.cpu().detach().numpy()
    thr = thr.tolist()
    try:
        start = thr.index(1)
        end = len(thr) - thr[::-1].index(1)

        # trimming the silences
        x_start = int(np.clip(start - margin, 0, None))
        x_end = end + margin
        y = x[..., x_start:x_end]
        return y
    except ValueError:
        # no value found
        return x
