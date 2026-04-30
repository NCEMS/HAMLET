import numpy as np
import numpy.typing as npt

from scipy.special import logsumexp


def normalize(array: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    return array / np.sum(array)


# normalization of log probabilities
def log_normalize(array: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    try:
        y = np.exp(array - logsumexp(array))

    except FloatingPointError:
        print(array)
        y = np.exp(array - logsumexp(array))
    return y


def avoid_underflow(array: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    array[array < 1e-30] = 1e-30
    return array
