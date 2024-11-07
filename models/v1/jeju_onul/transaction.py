from pydantic import BaseModel, Field, NonNegativeInt, NonNegativeFloat

from enum import Enum
import random

from dependencies.types import Profile
from models.v1.jeju_onul.algorithm import Algorithm

import env

Coordinate = tuple[float, float]

def CoordinateField(description: str | None = None):
    return Field(
        description=description,
        examples=[(random.uniform(126.0, 128.0), random.uniform(35.0, 38.0))],
    )

class WorkStatusType(Enum):
    waiting = 'waiting'
    shipped = 'shipped'
    assembly = 'assembly'
    done = 'done'
    handle_pickup = 'handle_pickup'
    handle_delivery = 'handle_delivery'

class TaskType(Enum):
    pickup = "pickup"
    delivery = "delivery"
    arrival = "arrival"
    departure = "departure"
    waiting = "waiting"

class CurrentStatus(Enum):
    wait = "wait"
    wave_1 = "wave_1"
    stopover = "stopover"
    wave_2 = "wave_2"

class Task(BaseModel):
    work_id: NonNegativeInt | None = Field(None)
    type: TaskType
    eta: NonNegativeInt
    duration: NonNegativeFloat = 0
    distance: NonNegativeFloat = 0
    setup_time: NonNegativeInt = 0
    service_time: NonNegativeInt = 0
    assembly_id: NonNegativeInt | None = Field(None)
    location: Coordinate = CoordinateField()
    done: bool | None = Field(
        default=False,
        description='이미 처리된 task인 경우 `done=true`',
    )

class Vehicle(BaseModel):
    id: NonNegativeInt = Field(
        examples=[0],
    )
    profile: Profile = Field(
        default=Profile.car,
    )
    location: Coordinate = CoordinateField(
        description='차량의 현재위치',
    )
    capacity: list[int] | None = Field(None)

class WorkPoint(BaseModel):
    location: Coordinate = CoordinateField(
        description='처리 위치',
    )
    group: str
    setup_time: NonNegativeInt = Field(
        default=0,
    )
    service_time: NonNegativeInt = Field(
        default=0,
    )

class WorkStatus(BaseModel):
    type: WorkStatusType
    vehicle_id: NonNegativeInt | None = Field(
        default=None,
        description='`type: "shipped"` 인 경우 선적한 차량의 `id`',
    )
    assembly_id: NonNegativeInt | None = Field(
        default=None,
        description='`type: "assembly"` 인 경우 현재 집결지의 `id`',
    )


class Work(BaseModel):
    id: NonNegativeInt = Field(examples=[0])
    description: str = Field('')
    pickup: WorkPoint
    delivery: WorkPoint
    amount: list[int] | None = Field(None)
    status: WorkStatus

class Assembly(BaseModel):
    id: NonNegativeInt = Field(examples=[0])
    location: Coordinate = CoordinateField()

class VehicleSchedule(BaseModel):
    id: NonNegativeInt = Field(
        examples=[0],
    )
    from_assembly_id: NonNegativeInt = Field(
        description='현재 스케줄의 시작 시점에 차량이 출발해야 하는 `Assembly`의 `id`',
    )
    to_assembly_id: NonNegativeInt | None = Field(
        default=None,
        description='현재 스케줄의 종료 시점에 차량이 도착해야 하는 `Assembly`의 `id`',
    )
    group: str | None = Field(
        default=None,
        description='현재 스케줄에서 차량이 담당하는 권역. 미입력시 권역 해제',
    )
    tasks: list[Task]
    up: list[NonNegativeInt] | None = Field(
        default=None,
        description='이전 최적화에서 현재 wave에 싣고 출발하는 목록',
    )
    down: list[NonNegativeInt] | None = Field(
        default=None,
        description='이전 최적화에서 현재 wave 끝나고 내리는 목록',
    )
    running: bool = Field(
        default=True,
        description='현재 스케줄에서 이 차량이 tasks의 완료되지 않은 첫 주문을 처리하려고 움직이는 중인지 여부. false인 경우 차량의 현재 위치 기준으로 계산'
    )

    def first_undone_task(self) -> Task | None:
        for t in self.tasks:
            if not t.done and t.type in [TaskType.pickup, TaskType.delivery]:
                return t

PRIORITY_MUST_HAVE_TO = 99
PRIORITY_HIGHEST = 40
PRIORITY_HIGH = 30
PRIORITY_MEDIUM = 20
PRIORITY_LOW = 10
PRIORITY_LOWEST = 0

class Priorities(BaseModel):
    waiting_shipment: int = Field(
        default=PRIORITY_HIGH,
        description='아직 pickup을 처리하지 않았고, 권역 내에서 shipment로 처리 예정인 주문에 대한 priority',
    )
    waiting_pickup: int = Field(
        default=PRIORITY_HIGHEST,
        description='아직 pickup을 처리하지 않았고, job으로 분리하여 처리하는 주문에 대한 priority',
    )

    handle_pickup_shipment: int = Field(
        default=PRIORITY_MUST_HAVE_TO,
        description='아직 pickup을 처리하지 않았고, 권역 내에서 shipment로 처리하며 현재 차량이 pickup을 하기 위해 향하고 있는 주문에 대한 priority',
    )
    handle_pickup_pickup: int = Field(
        default=PRIORITY_MUST_HAVE_TO,
        description='아직 pickup을 처리하지 않았고, job으로 처리하며 현재 차량이 pickup을 하기 위해 향하고 있는 주문에 대한 priority',
    )

    handle_delivery_delivery: int = Field(
        default=PRIORITY_MUST_HAVE_TO,
        description='현재 차량에 싣고 있고, 차량이 delivery를 하기 위해 향하고 있는 주문에 대한 priority',
    )

    shipped_delivery: int = Field(
        default=PRIORITY_MEDIUM,
        description='현재 차량에 싣고 있고, 해당 차량이 배송 예정인 주문에 대한 priority',
    )

    assembly_shipment: int = Field(
        default=PRIORITY_MEDIUM,
        description='현재 집결지에서 대기중이고, 추후 실은 차량이 배송해야하는 주문에 대한 priority',
    )
    assembly_pickup: int = Field(
        default=PRIORITY_HIGHEST,
        description='현재 집결지에서 대기중이고, 집결지에 있는 차량이 처리할 수 없어 다음 집결지로 향해야 하는 주문에 대한 priority',
    )

class AssemblyStopoverTime(BaseModel):
    assembly_id: NonNegativeInt = Field()
    stopover_time: NonNegativeInt = Field()

class Schedule(BaseModel):
    start: NonNegativeInt | None = Field(
        default=None,
        description='스케줄 시작 시간 (in unixtimestamp millis)',
        examples=[1692745200],
    )
    end: NonNegativeInt | None = Field(
        default=None,
        description='스케줄 종료 시간 (in unixtimestamp millis)',
        examples=[1692758700],
    )
    vehicles: list[VehicleSchedule]
    # priorities: Priorities = Field(
    #     default=Priorities(),
    # )
    # divide_shipment: bool = Field(
    #     default=False,
    #     description='동일 권역 내에서 shipment 처리 가능한 주문도 pickup, delivery로 분리하여 처리 여부 설정',
    # )
    assembly_stopover_time: list[AssemblyStopoverTime] | None = Field(
        default=None,
        description='for `wave 2`, `wave 1`이 종료된 상태에서는 집결 시간이 확정된 상황으로 기존에 계산된 집결 시간을 입력 받는다.'
    )
    stopover_waiting_time: NonNegativeInt = Field(
        default=900,
        description='`wave 2`와 `wave 3` 사이에 집결할 때 배분하는 시간, default=15분'
    )

class Schedules(BaseModel):
    wave_1: Schedule = Field(
        description='''
pickup 우선 처리, 고정 시간 출발, 고정 시간 도착 (`start`, `end` required)\n
`start: 08:00 ~ end: 11:45` 에 해당하는 시간 입력
''',
    )
    wave_2: Schedule = Field(
        description='''
pickup 우선 처리, 고정 시간 출발, Assembly별 변동 시간 도착 (`start` required)\n
`start: 13:00` 에 해당하는 시간 입력
''',
    )
    wave_3: Schedule = Field(
        description='''
모든 주문 처리, Assembly별 변동 시간 출발, 모든 업무 완료 후 종료
''',
    )

class Request(BaseModel):
    current_time: NonNegativeInt = Field(
        description='현재 시간 (in unixtimestamp millis)'
    )
    current_status: CurrentStatus = Field(
        default=CurrentStatus.wait,
        description='''현재 상태\n
`wait`: 배송 시작 전\n
`wave_1`: 첫 번째 `wave` 시작한 상태\n
`stopover`: `wave 1` 종료 후 집결한 상태\n
`wave_2`: 두 번째 `wave` 시작 이후
''',
    )
    vehicles: list[Vehicle] = Field(
        description='차량 정보',
    )
    works: list[Work]
    assemblies: list[Assembly]
    schedules: Schedules
    algorithm: Algorithm = Field(
        default=Algorithm(),
    )

class VehicleTasks(BaseModel):
    vehicle_id: NonNegativeInt
    tasks: list[Task]

class VehicleSwaps(BaseModel):
    vehicle_id: NonNegativeInt
    assembly_id: NonNegativeInt
    stopover_time: NonNegativeInt | None = Field(
        default=None,
        description='집결 시간',
    )
    down: list[NonNegativeInt] = Field(
        description='Assembly에서 차량이 내려놓을 주문의 work_id list'
    )
    up: list[NonNegativeInt] = Field(
        description='Assembly에서 차량이 실어야 할 주문의 work_id list'
    )

class Response(BaseModel):
    v: str = Field(default=env.VERSION)
    wave_1: list[VehicleTasks]
    swap_1_2: list[VehicleSwaps]
    wave_2: list[VehicleTasks]
    swap_2_3: list[VehicleSwaps]
    wave_3: list[VehicleTasks]
