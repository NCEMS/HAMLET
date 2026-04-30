from typing import Optional, Tuple, Union
import numpy as np
import numpy.typing as npt

def logsumexp(
    a: npt.ArrayLike,
    axis: Optional[Union[int, Tuple[int, ...]]] = None,
    b: Optional[npt.ArrayLike] = None,
    keepdims: bool = False,
    return_sign: bool = False
) -> Union[npt.NDArray[np.float64], Tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]]:
    ...
