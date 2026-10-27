"""SKELETON: minimal custom-model structure.

This file intentionally does not run.  Complete the physical equations,
initialization, group registration, and reference tests, then run
``andes prepare -i`` before importing the model into a study.  Do not copy this
into a production model and assume the placeholder ``Algeb`` equation is
physically meaningful.
"""
from andes.core.model import Model, ModelData
from andes.core.param import IdxParam, NumParam
from andes.core.var import Algeb


class MyModelData(ModelData):
    def __init__(self):
        super().__init__()
        self.bus = IdxParam(model="Bus", mandatory=True)
        self.k = NumParam(default=1.0, info="Example gain")


class MyModel(MyModelData, Model):
    def __init__(self, system, config):
        MyModelData.__init__(self)
        Model.__init__(self, system, config)
        self.group = "Undefined"  # Replace with a justified group or create/register one.
        self.flags.pflow = True
        # Placeholder only: replace with the governing equation and units.
        self.y = Algeb(v_str="0", e_str="-y", tex_name="y")


if __name__ == "__main__":
    raise SystemExit(
        "SKELETON: define physical equations, initialization, registration, and reference "
        "tests; then run `andes prepare -i`."
    )
