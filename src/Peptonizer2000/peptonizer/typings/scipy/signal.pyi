from typing import Union, Optional, Sequence
import numpy as np
import numpy.typing as npt

def fftconvolve(
    in1: npt.ArrayLike,
    in2: npt.ArrayLike,
    mode: str = 'full',
    axes: Optional[Union[int, Sequence[int]]] = None
) -> npt.NDArray[np.float64]:
    ...