from Box.boxes import gen_STE, gen_RSC, gen_OTE
from Cardboard.material import Material, Tooling
from render_preview import render_preview


def main():
    
    dlOTE = gen_OTE(
        dim=dict(L=100, W=50, H=150),
        material=Material(thickness=3),
        tooling=Tooling(),
    )
    
    dlSTE = gen_STE(
        dim=dict(L=100, W=50, H=150),
        material=Material(thickness=3),
        tooling=Tooling(),
    )

    dlRSC = gen_RSC(
        dim=dict(L=200, W=100, H=150),
        material=Material(thickness=3),
        tooling=Tooling(),
    )

   
   # render_preview(dlOTE)
   # render_preview(dlSTE)
    render_preview(dlRSC)


if __name__ == "__main__":
    main()
