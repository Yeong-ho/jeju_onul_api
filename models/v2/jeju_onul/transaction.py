from pydantic import BaseModel, Field, NonNegativeInt, NonNegativeFloat

from enum import Enum
import random

from dependencies.types import Profile

import env

# schema
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel, Field
from typing import NamedTuple, Optional
import pytz


class TaskType(Enum):
    pickup = "pickup"
    delivery = "delivery"
    arrival = "arrival"
    departure = "departure"
    waiting = "waiting"

class WorkStatusType(Enum):
    waiting = 'waiting'
    """아무 액션도 없는 상태\n
    (`pickup.location`에 있음)"""

    shipped = 'shipped'
    """vehicle_id 차량에 실려있음\n
    (`vehicle.current_location`에 있음)"""

    stopped = 'stopped'
    """실려가다가 어떠한 사유로 내려짐\n
    (`location`에 있음, 차량 고장 등으로 다른 차가 처리 필요할 때)"""

    done = 'done'
    """완료\n
    (`location`에 있음, 특별한 사유가 없다면 `delivery.location`과 같다)"""


class Coordinates(NamedTuple):
    longitude: float
    latitude: float

def CoordinatesField(description: str | None = None):
    return Field(
        description=description,
        examples=[(random.uniform(126.0, 128.0), random.uniform(35.0, 38.0))],
)

class WorkPoint(BaseModel):
    location: Coordinates
    setup_time: timedelta = Field(
        default=timedelta(minutes=0),
    )
    service_time: timedelta = Field(
        default=timedelta(minutes=5),
    )
    group_id: str = Field(
        default='',
    )

    def to_job(self, index: int) -> dict:
        return {
            'id': index,
            'location': self.location,
            'setup': int(self.setup_time.total_seconds()),
            'service': int(self.service_time.total_seconds())
        }

    def get_group(self) -> str:
        return self.group_id


class WorkStatus(BaseModel):
    type: WorkStatusType = Field(
        default=WorkStatusType.waiting,
    )
    vehicle_id: Optional[str] = Field(
        default=None,
    )
    location: Optional[Coordinates] = Field(
        default=None,
    )

class Task(BaseModel):
    work_id: Optional[str] = Field(None)
    type: TaskType
    eta: NonNegativeInt
    duration: NonNegativeInt = 0
    distance: NonNegativeInt = 0
    setup_time: NonNegativeInt = 0
    service_time: NonNegativeInt = 0
    assembly_id: Optional[str] = Field(None)
    location: Coordinates = CoordinatesField()



class Work(BaseModel):
    id: str = Field()
    pickup: WorkPoint = Field()
    delivery: WorkPoint = Field()
    amount: Optional[list[int]] = Field(
        default=None,
    )
    status: WorkStatus = Field(
        default=WorkStatus(),
    )
    exception: bool = Field(
        default=False,
        description='제외 권역과 무관하게 강제 배차 시키는 주문 설정',
    )
    fix_vehicle_id: Optional[str] = Field(
        default=None,
        description='특정 차량에 고정 배차 시키는 주문 설정',
    )


class RoutingProfile(Enum):
    car = 'car'
    """Use OSRM Car Profile"""

    atlan = 'atlan'
    """Use Atlan API Wrapper"""


class Vehicle(BaseModel):
    id: str = Field()
    profile: RoutingProfile = Field(
        default=RoutingProfile.car
    )
    current_location: Coordinates = Field()
    capacity: Optional[list[int]] = Field(
        default=None,
    )
    include: list[str] = Field(
        default=[],
    )
    exclude: list[str] = Field(
        default=[],
    )
    home: Optional[Coordinates] = Field(
        default=None,
    )


class Assembly(BaseModel):
    id: str = Field()
    location: Coordinates = Field()
    capacity: int = Field(
        default=0,
    )


class Boundary(BaseModel):
    id: str = Field()
    polygon: list[Coordinates]


class Request(BaseModel):
    current_time: datetime = Field(
        description='현재 시각',
        examples=[
            datetime.fromisoformat('2024-01-25T11:11:46.000+09:00'),
            datetime.fromtimestamp(1706148919, pytz.timezone('Asia/Seoul')),
            datetime.fromtimestamp(1706148919),
        ],
    )
    works: list[Work] = Field()
    vehicles: list[Vehicle] = Field()
    assemblies: list[Assembly] = Field()
    boundaries: list[Boundary] = Field()

class VehicleTasks(BaseModel):
    vehicle_id: str
    tasks: list[Task]

class VehicleSwaps(BaseModel):
    vehicle_id : str
    assembly_id :str
    stopover_time : NonNegativeInt
    down : list[str]
    up : list[str]

class Start_Response(BaseModel):
    vehicle_tasks: list[VehicleTasks] = Field()
    unassigned: list[str]=Field()

class End_Response(BaseModel):
    before_tasks: list[VehicleTasks] = Field(default=[])
    after_tasks: list[VehicleTasks] = Field(default=[])
    swaps: list[VehicleSwaps] = Field(default=[])
