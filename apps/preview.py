from apps.Box.boxes import gen_RSC
from apps.Cardboard.material import Material, Tooling
from render_svg import render

dl = gen_RSC(
    dim=dict(L=434, W=214, H=278),
    material=Material(thickness=3),
    tooling=Tooling()
)

render(dl)
