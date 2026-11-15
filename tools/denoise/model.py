"""The residual model: predicts the whitened difference image from references and a blind ring.

    g(p) = head( ref_branch(reference channels, frame scalars)(p),
                 donut(pointwise embedding of all channels)(p) )

The reference branch is an ordinary 3x3 conv stack: its inputs come from other passes, so it
may look anywhere. The search frame itself enters only through two "donut" convolutions whose
weights are zero within HOLE px of the centre (a dense 13x13 kernel and a dilation-3 9x9
kernel for wider context), applied to a pointwise embedding and followed only by 1x1
convolutions. So g(p) cannot depend on the search frame within HOLE px of p: a point source
at p that is absent from the references cannot be predicted and so is not subtracted, and
the noise at p (correlated over ~1 px by resampling) cannot be copied. `blind_check` tests
this numerically. All torch imports are inside functions.
"""

from __future__ import annotations

from typing import Any

HOLE = 2  # Chebyshev radius (px) around the predicted pixel hidden from the model
WIDTH = 48
EMBED = 16
N_REF_LAYERS = 5


def build_model() -> Any:
    import torch
    from torch import nn

    from .features import BLIND, CHANNELS, N_SCALARS, REF

    def donut_mask(k: int, dilation: int) -> torch.Tensor:
        c = k // 2
        off = (torch.arange(k) - c).abs() * dilation
        hidden = (off[:, None] <= HOLE) & (off[None, :] <= HOLE)
        return (~hidden).float()[None, None]

    class Donut(nn.Conv2d):
        def __init__(self, cin: int, cout: int, k: int, dilation: int = 1) -> None:
            super().__init__(cin, cout, k, padding=dilation * (k // 2), dilation=dilation,
                             bias=False)
            self.register_buffer("hole", donut_mask(k, dilation))

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return nn.functional.conv2d(x, self.weight * self.hole, None, 1, self.padding,
                                        self.dilation)

    class Net(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            cin = len(REF) + N_SCALARS
            layers: list[nn.Module] = []
            for i in range(N_REF_LAYERS):
                layers += [nn.Conv2d(cin if i == 0 else WIDTH, WIDTH, 3, padding=1), nn.GELU()]
            self.ref = nn.Sequential(*layers)
            self.embed = nn.Sequential(nn.Conv2d(len(CHANNELS), EMBED, 1), nn.GELU())
            self.near = Donut(EMBED, WIDTH, 13)
            self.far = Donut(EMBED, WIDTH, 9, dilation=3)
            self.head = nn.Sequential(nn.Conv2d(3 * WIDTH, WIDTH, 1), nn.GELU(),
                                      nn.Conv2d(WIDTH, WIDTH, 1), nn.GELU(),
                                      nn.Conv2d(WIDTH, 1, 1))
            nn.init.zeros_(self.head[-1].weight)  # start at g = 0, the current method
            nn.init.zeros_(self.head[-1].bias)
            self.ref_idx, self.blind_idx = list(REF), list(BLIND)

        def forward(self, x: torch.Tensor, scal: torch.Tensor) -> torch.Tensor:
            """x (B, 7, H, W), scal (B, N_SCALARS) -> g (B, H, W) in whitened units."""
            s = scal[:, :, None, None].expand(-1, -1, x.shape[2], x.shape[3])
            a = self.ref(torch.cat([x[:, self.ref_idx], s], dim=1))
            e = self.embed(x)
            return self.head(torch.cat([a, self.near(e), self.far(e)], dim=1))[:, 0]

    return Net()


def n_params(model: Any) -> int:
    return int(sum(p.numel() for p in model.parameters()))


def blind_check(model: Any, size: int = 41) -> float:
    """Largest change of g within HOLE px of a pixel when the blind channels are changed at
    that pixel (must be 0), for random weights in the output layer. Returns that maximum."""
    import copy

    import torch

    from .features import BLIND, CHANNELS, N_SCALARS

    m = copy.deepcopy(model).cpu().double().eval()
    torch.manual_seed(0)
    torch.nn.init.normal_(m.head[-1].weight, std=0.1)
    x = torch.randn(1, len(CHANNELS), size, size, dtype=torch.double)
    scal = torch.randn(1, N_SCALARS, dtype=torch.double)
    c = size // 2
    y = x.clone()
    y[0, list(BLIND), c, c] += 5.0
    with torch.no_grad():
        d = (m(x, scal) - m(y, scal)).abs()[0]
    far = float(d.max())
    if far <= 0:
        raise AssertionError("blind check is vacuous: the perturbation changed nothing")
    return float(d[c - HOLE:c + HOLE + 1, c - HOLE:c + HOLE + 1].max())


def predict(model: Any, x: Any, scal: Any, batch: int = 16) -> Any:
    """g for numpy inputs (n, 7, H, W), (n, N_SCALARS) -> numpy (n, H, W) float32, on CPU."""
    import numpy as np
    import torch

    model = model.cpu().float().eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            g = model(torch.from_numpy(x[i:i + batch]), torch.from_numpy(scal[i:i + batch]))
            out.append(g.numpy())
    return np.concatenate(out).astype(np.float32)
