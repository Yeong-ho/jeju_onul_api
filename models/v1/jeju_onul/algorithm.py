from pydantic import BaseModel, Field, NonNegativeInt, NonNegativeFloat

from enum import Enum

class SecondAssemblyAlgorithmType(Enum):
    handle_pickup = 'handle_pickup'
    select_best = 'select_best'

class SecondAssemblyAlgorithm(BaseModel):
    type: SecondAssemblyAlgorithmType = Field(
        default=SecondAssemblyAlgorithmType.handle_pickup,
    )
    assembly_time_candidates: list[int] = Field(
        default=[7200, 10800, 14400, 18000],
    )

class Algorithm(BaseModel):
    second_assembly: SecondAssemblyAlgorithm = Field(
        default=SecondAssemblyAlgorithm(),
    )
