from fastapi import HTTPException
from http import HTTPStatus

from .transaction import *

import dependencies.vroouty as vroouty
import dependencies.osrm as osrm

class Wave:
    vehicles: list[VehicleSchedule]
    vehicles_dict = dict[int, VehicleSchedule]

    __vehicle_index_prefix: int
    __vehicle_indexes: dict[int, int]

    start_time: int | None
    end_time: int | None

    assembly_stopover_times: dict[int, int] | None = None
    stopover_waiting_time: int | None = None

    def __init__(
            self,
            schedule: Schedule,
            vehicle_index_prefix: int,
            ) -> None:
        self.vehicles = schedule.vehicles
        self.vehicles_dict = { v.id: v for v in schedule.vehicles }

        self.__vehicle_index_prefix = vehicle_index_prefix
        self.__vehicle_indexes = {}

        for i, v in enumerate(self.vehicles):
            self.__vehicle_indexes[v.id] = i

        self.start_time = schedule.start
        self.end_time = schedule.end

        if schedule.assembly_stopover_time is not None:
            self.assembly_stopover_times = {
                ast.assembly_id: ast.stopover_time for ast in schedule.assembly_stopover_time
            }
        if schedule.stopover_waiting_time is not None:
            self.stopover_waiting_time = schedule.stopover_waiting_time

    def vehicle_id_to_index(self, id: int) -> int:
        return self.__vehicle_index_prefix + self.__vehicle_indexes[id]

    def vehicle_index_to_id(self, index: int) -> int:
        return self.vehicles[index - self.__vehicle_index_prefix].id

class Waves:
    WAVE_1_PREFIX = 10000
    WAVE_2_PREFIX = 20000
    WAVE_3_PREFIX = 30000

    w1: Wave
    w2: Wave
    w3: Wave

    def __init__(self, schedules: Schedules) -> None:
        self.w1 = Wave(schedules.wave_1, self.WAVE_1_PREFIX)
        self.w2 = Wave(schedules.wave_2, self.WAVE_2_PREFIX)
        self.w3 = Wave(schedules.wave_3, self.WAVE_3_PREFIX)

    def vehicle_index_to_id(self, index: int) -> tuple[int, int]:
        if index >= self.WAVE_3_PREFIX:
            return 3, self.w3.vehicle_index_to_id(index)
        if index >= self.WAVE_2_PREFIX:
            return 2, self.w2.vehicle_index_to_id(index)
        else:
            return 1, self.w1.vehicle_index_to_id(index)

class Skills:
    __unique_skill_id: int
    __skills: dict[str, int]
    __waves: list[int]
    __vehicles: list[int]
    __group_vehicles: dict[str, set[tuple[int, int]]]
    __assembly_visits: dict[int, dict[str, dict[int, set[int]]]]

    def __init__(
            self,
            vehicles: list[Vehicle],
            assemblies: list[Assembly],
            schedules: Schedules,
            ) -> None:
        waves = [1, 2, 3]

        self.__unique_skill_id = 0
        self.__skills = {}

        self.__waves = [ w for w in waves ]
        self.__vehicles = [ v.id for v in vehicles ]
        self.__group_vehicles = {}
        self.__assembly_visits = {}

        for w in waves:
            self.__assembly_visits[w] = { 's': {}, 'e': {} }

            for v in vehicles:
                self.add_key(self.__wave_vehicle_neg_key(w, v.id))

                for a in assemblies:
                    self.__assembly_visits[w]['s'][a.id] = set()
                    self.__assembly_visits[w]['e'][a.id] = set()

        sw: list[tuple[Schedule, int]] = [(schedules.wave_1, 1), (schedules.wave_2, 2), (schedules.wave_3, 3)]

        for s, w in sw:
            for v in s.vehicles:
                if v.group not in self.__group_vehicles:
                    self.__group_vehicles[v.group] = set()
                self.__group_vehicles[v.group].add((w, v.id))

                self.__assembly_visits[w]['s'][v.from_assembly_id].add(v.id)
                if v.to_assembly_id is not None:
                    self.__assembly_visits[w]['e'][v.to_assembly_id].add(v.id)

        self.__skill_ids = {v: k for k, v in self.__skills.items()}

        print('skills', self.__skills)
        print('skill_ids', self.__skill_ids)
        print('assembly_visits', self.__assembly_visits)
        print('group_vehicles', self.__group_vehicles)

    def __wave_vehicle_neg_key(self, w: int, v: int) -> str:
        return f'!w{w}-v{v}'

    def add_key(self, key: str):
        if key not in self.__skills:
            self.__skills[key] = self.__unique_skill_id
            self.__unique_skill_id += 1

    def get_vehicle_skills(self, wave: int, vehicle: VehicleSchedule) -> list[int]:
        skills = set()

        for w in self.__waves:
            for v in self.__vehicles:
                if w == wave and v == vehicle.id:
                    continue
                skills.add(self.__skills[self.__wave_vehicle_neg_key(w, v)])

        return sorted(list(skills))

    def get_task_skills_wave_vehicles(self, wave_vehicles: list[tuple[int, int]]) -> list[int]:
        skills = set()

        for w in self.__waves:
            for v in self.__vehicles:
                if (w, v) in wave_vehicles:
                    continue
                skills.add(self.__skills[self.__wave_vehicle_neg_key(w, v)])

        print('wave_vehicles', wave_vehicles)
        return sorted(list(skills))

    def get_task_skills_assembly_visits(
            self,
            work: Work, assembly_visits: list[tuple[int, str, int]],
            pickup_group: bool, delivery_group: bool,
            ) -> list[int]:
        skills = set()

        accessable_wave_vehicles = set()

        for w, s, a in assembly_visits:
            for v in self.__assembly_visits[w][s][a]:
                if pickup_group and (w, v) not in self.__group_vehicles[work.pickup.group]:
                    continue
                if delivery_group and (w, v) not in self.__group_vehicles[work.delivery.group]:
                    continue
                accessable_wave_vehicles.add((w, v))

        print('assembly_visits')
        skills = skills.union(self.get_task_skills_wave_vehicles(list(accessable_wave_vehicles)))

        return sorted(list(skills))

    def get_task_skills_meet_shipped_vehicle(
            self,
            work: Work, wave: int, vehicle: int,
            shipped_can_deliver: bool,
            ) -> list[int]:
        skills = set()

        accessable_wave_vehicles = set()

        if shipped_can_deliver and (wave, vehicle) in self.__group_vehicles[work.delivery.group]:
            accessable_wave_vehicles.add((wave, vehicle))

        for w in range(wave+1, 4):
            for _, vs in self.__assembly_visits[w]['s'].items():
                if vehicle not in vs:
                    continue

                for v in vs:
                    if (w, v) not in self.__group_vehicles[work.delivery.group]:
                        continue
                    for ww in range(w, 4):
                        accessable_wave_vehicles.add((ww, v))

        print(wave, vehicle, shipped_can_deliver, accessable_wave_vehicles)

        print('meet_shipped_vehicle')
        skills = skills.union(self.get_task_skills_wave_vehicles(list(accessable_wave_vehicles)))

        return sorted(list(skills))

    def get_task_skills_waiting_pickup(self, w: Work):
        skills = set()

        accessable_wave_vehicles = set()

        # pickup 위치의 그룹에 속한 차량만 처리 가능
        for pw, pv in self.__group_vehicles[w.pickup.group]:
            # pickup은 wave3에서는 처리되지 않음
            if pw not in [1, 2]:
                continue

            for dw, dv in self.__group_vehicles[w.delivery.group]:
                if pv != dv and pw >= dw:
                    continue
                if pv == dv and pw > dw:
                    continue

                # pw wave에 도착하는 assembly들에 대해 체크
                for _, vs in self.__assembly_visits[pw]['e'].items():
                    # pv, dv가 만나는 경우
                    if pv not in vs or dv not in vs:
                        continue
                    # 해당 차량이 pickup 가능
                    accessable_wave_vehicles.add((pw, pv))

        print('waiting_pickup')
        skills = skills.union(self.get_task_skills_wave_vehicles(list(accessable_wave_vehicles)))

        return sorted(list(skills))

    def get_task_skills_waiting_shipment(self, w: Work):
        skills = set()

        accessable_wave_vehicles = set()

        # 같은 그룹에 속한 차량만 처리 가능
        for w, v in self.__group_vehicles[w.pickup.group]:
            # pickup이 wave3에서는 처리되지 않음
            # pickup과 같은 차량으로 처리된 shipment만 채택되므로 불필요
            if w not in [1, 2]:
                continue

            accessable_wave_vehicles.add((w, v))

        print('waiting_shipment')
        skills = skills.union(self.get_task_skills_wave_vehicles(list(accessable_wave_vehicles)))

        return sorted(list(skills))

class WorkHandler:
    __unique_index: int

    __id_to_index: dict
    __index_to_id: dict

    def __init__(self) -> None:
        self.__unique_index = 0

        self.__id_to_index = {}
        self.__index_to_id = {}

    def __setup_key(self, key) -> int:
        if key not in self.__id_to_index:
            idx = self.__unique_index
            self.__unique_index += 1
            self.__id_to_index[key] = idx
            self.__index_to_id[idx] = key

        return self.__id_to_index[key]

    def pickup_index(self, work_id: int) -> int:
        return self.__setup_key(('pickup', work_id))

    def delivery_index(self, work_id: int) -> int:
        return self.__setup_key(('delivery', work_id))

    def shipment_pickup_index(self, work_id: int) -> int:
        return self.__setup_key(('shipment_pickup', work_id))

    def shipment_delivery_index(self, work_id: int) -> int:
        return self.__setup_key(('shipment_delivery', work_id))

    def shipment_assembly_index(self, work_id: int) -> int:
        return self.__setup_key(('shipment_assembly', work_id))

    def dummy_index(self, wave: int, vehicle_id: int) -> int:
        return self.__setup_key(('dummy', wave, vehicle_id))

    def work_id(self, index: int) -> tuple[str, int]:
        return self.__index_to_id[index]

    def is_dummy(self, index: int) -> bool:
        return self.__index_to_id[index][0] in ['dummy', 'shipment_assembly']

class OptimizationHandler:
    vehicle_dict: dict[int, Vehicle]
    assembly_dict: dict[int, Assembly]
    work_dict: dict[int, Work]

    skills: Skills
    work_handler: WorkHandler

    waves: Waves

    wave_1_done_pickups: dict[int, int]
    wave_1_done_deliveries: dict[int, int]
    wave_1_departed: set[int]
    wave_1_arrived: set[int]
    wave_1_pickups: dict[int, int]
    wave_1_shipments: dict[int, int]
    swap_1_2_down: dict[int, int]
    swap_1_2_up: dict[int, int]
    wave_2_pickups: dict[int, int]
    wave_2_shipments: dict[int, int]
    wave_2_stopover_times: dict[int, int]
    swap_2_3_down: dict[int, int]
    swap_2_3_up: dict[int, int]

    def __init__(self, request: Request) -> None:
        self.vehicle_dict = { v.id: v for v in request.vehicles }
        self.assembly_dict = { a.id: a for a in request.assemblies }
        self.work_dict = { w.id: w for w in request.works }

        self.skills = Skills(request.vehicles, request.assemblies, request.schedules)
        self.work_handler = WorkHandler()

        self.waves = Waves(request.schedules)

        self.wave_1_done_pickups = {}
        self.wave_1_done_deliveries = {}
        self.wave_1_departed = set()
        self.wave_1_arrived = set()
        self.wave_1_pickups = {}
        self.wave_1_shipments = {}
        self.swap_1_2_down = {}
        self.swap_1_2_up = {}
        self.wave_2_pickups = {}
        self.wave_2_shipments = {}
        self.wave_2_stopover_times = {}
        self.swap_2_3_down = {}
        self.swap_2_3_up = {}

        for vs in self.waves.w1.vehicles:
            for t in vs.tasks:
                if t.done:
                    if t.type == TaskType.pickup:
                        self.wave_1_done_pickups[t.work_id] = vs.id
                    if t.type == TaskType.delivery:
                        self.wave_1_done_deliveries[t.work_id] = vs.id
                    if t.type == TaskType.departure:
                        self.wave_1_departed.add(vs.id)
                    if t.type == TaskType.arrival:
                        self.wave_1_arrived.add(vs.id)

        if request.current_status in [CurrentStatus.stopover]:

            for vs in self.waves.w1.vehicles:
                for d in vs.down:
                    self.swap_1_2_down[d] = vs.id

            for vs in self.waves.w2.vehicles:
                for u in vs.up:
                    self.swap_1_2_up[u] = vs.id
                for d in vs.down:
                    self.swap_2_3_down[d] = vs.id

            for vs in self.waves.w3.vehicles:
                for u in vs.up:
                    self.swap_2_3_up[u] = vs.id

    def prune_skills(self, request):
        # 모든 주문에 사용된 skill의 합집합
        used_skills_union: set[int] = set()

        for j in request['jobs']:
            used_skills: set[int] = set()
            for skill in j['skills']:
                used_skills.add(skill)

            used_skills_union = used_skills_union.union(used_skills)

        for s in request['shipments']:
            used_skills: set[int] = set()
            for skill in s['skills']:
                used_skills.add(skill)

            used_skills_union = used_skills_union.union(used_skills)

        # 모든 차량이 가지고 있는 skill (불필요)
        used_skills_intersects: set[int] | None = None

        for v in request['vehicles']:
            used_skills: set[int] = set()
            for skill in v['skills']:
                used_skills.add(skill)

            if used_skills_intersects is None:
                used_skills_intersects = used_skills
            else:
                used_skills_intersects = used_skills_intersects.intersection(used_skills)

        if used_skills_intersects is None:
            used_skills_intersects = set()

        # 주문에 사용된 skill 중, 모든 차량이 가지고 있는 skill을 제거한다
        used_skills_union = used_skills_union.difference(used_skills_intersects)

        print('prune:', 'intersects:', used_skills_intersects, 'difference:', used_skills_union)

        for i, j in enumerate(request['jobs']):
            request['jobs'][i]['skills'] = list(used_skills_union.intersection(j['skills']))

        for i, s in enumerate(request['shipments']):
            request['shipments'][i]['skills'] = list(used_skills_union.intersection(s['skills']))

        for i, v in enumerate(request['vehicles']):
            request['vehicles'][i]['skills'] = list(used_skills_union.intersection(v['skills']))

    async def minimum_end_time(
            self,
            request: dict,
            start: int,
            minimum_time_vehicles: set[int],
            must_handle_ids: set[int],
        ):
        self.prune_skills(request)

        best_response: dict = {}

        original_vehicles = [v.copy() for v in request['vehicles']]

        time_threshold = 1000

        l, r = start, start + 86400

        print('\t', 'minimum_time_vehicles:', minimum_time_vehicles)
        print('\t', 'must_handle:', must_handle_ids)

        while l + time_threshold < r:
            c = int((l + r)/2)

            print(l, c, r)

            for i, v in enumerate(request['vehicles']):
                if v['id'] in minimum_time_vehicles:
                    tw = original_vehicles[i]['time_window']

                    if tw[0] > c:
                        tw = (tw[0], tw[0])
                    else:
                        tw = (tw[0], c)

                    request['vehicles'][i]['time_window'] = tw
                    print('\t', 'vehicle', v['id'], 'tw:', tw)

            status, response = await vroouty.Post(request)

            if status != 200:
                raise HTTPException(500, detail=response)

            print('\t', 'unassigned:', [u['id'] for u in response['unassigned']])

            if any([u['id'] in must_handle_ids for u in response['unassigned']]):
                l = c
            else:
                r = c
                best_response = response

        return best_response

    async def setup_route_data_for_tasks(self, profile: str, tasks: list[Task]):

        # calculate osrm
        if len(tasks) > 1:
            status, response = await osrm.GetRoutes(profile, [t.location for t in tasks])
            if status == 200:
                for i, leg in enumerate(response['routes'][0]['legs']):
                    tasks[i+1].duration = leg['duration']
                    tasks[i+1].distance = leg['distance']

    async def first_optimization(self, request: Request):

        fo_vehicles = []
        fo_jobs = []
        fo_shipments = []

        fo_minimum_time_vehicles: set[int] = set()
        fo_must_handle_ids: set[int] = set()

        if request.current_status in [CurrentStatus.wait, CurrentStatus.wave_1]:

            for vs in self.waves.w1.vehicles:
                v = self.vehicle_dict[vs.id]

                if request.current_status == CurrentStatus.wave_1:

                    next_task = vs.first_undone_task()

                    running = vs.running if next_task is not None else False

                    if running and next_task.work_id is not None:
                        handling_work = self.work_dict[next_task.work_id]
                        if next_task.type == TaskType.pickup:
                            print(f'fo waiting pickup {handling_work.id} changed to handle_pickup, by vehicle {vs.id}')
                            handling_work.status.type = WorkStatusType.handle_pickup
                            handling_work.status.vehicle_id = vs.id
                        if next_task.type == TaskType.delivery:
                            print(f'fo waiting delivery {handling_work.id} changed to handle_delivery, by vehicle {vs.id}')
                            handling_work.status.type = WorkStatusType.handle_delivery
                            handling_work.status.vehicle_id = vs.id

                start = v.location
                if request.current_status == CurrentStatus.wait:
                    assembly = self.assembly_dict[vs.from_assembly_id]
                    start = assembly.location
                elif request.current_status == CurrentStatus.wave_1:
                    if running:
                        start = next_task.location

                vehicle = {
                    'id': self.waves.w1.vehicle_id_to_index(vs.id),
                    'profile': v.profile.value,
                    'start': start,
                    'end': self.assembly_dict[vs.to_assembly_id].location,
                    'skills': self.skills.get_vehicle_skills(1, vs),
                    'wave': 1,
                }

                if v.capacity is not None:
                    vehicle['capacity'] = v.capacity

                # wave 1 차량은 업무시간 wave 1 start ~ wave 1 end
                tw_start = self.waves.w1.start_time
                tw_end = self.waves.w1.end_time - 300

                if request.current_status == CurrentStatus.wave_1:
                    if running:
                        tw_start = next_task.eta
                        if tw_start < request.current_time:
                            tw_start = request.current_time
                    else:
                        tw_start = request.current_time

                # 실시간 스케줄 등의 이슈로 시간이 오버된 경우 최적화에서 제외
                # -> 하던 일만 하고 집결
                if tw_start < tw_end:
                    vehicle['time_window'] = (tw_start, tw_end)
                    fo_vehicles.append(vehicle)
                    fo_jobs.append({
                        'id': self.work_handler.dummy_index(1, vs.id),
                        'location': start,
                        'skills': self.skills.get_task_skills_wave_vehicles([(1, vs.id)]),
                    })

                print('fo w1 vehicle', vehicle)

        for vs in self.waves.w2.vehicles:
            v = self.vehicle_dict[vs.id]

            start = self.assembly_dict[vs.from_assembly_id].location
            end = self.assembly_dict[vs.to_assembly_id].location

            vehicle = {
                'id': self.waves.w2.vehicle_id_to_index(vs.id),
                'profile': v.profile.value,
                'start': start,
                'end': end,
                'skills': self.skills.get_vehicle_skills(2, vs),
                'wave': 2,
            }

            if v.capacity is not None:
                vehicle['capacity'] = v.capacity

            # wave 2 차량은 업무시간 wave 2 start ~ inf
            tw_start = self.waves.w2.start_time
            tw_end = tw_start + 86400

            vehicle['time_window'] = (tw_start, tw_end)
            fo_vehicles.append(vehicle)
            fo_jobs.append({
                'id': self.work_handler.dummy_index(2, vs.id),
                'location': start,
                'skills': self.skills.get_task_skills_wave_vehicles([(2, vs.id)]),
            })

            fo_minimum_time_vehicles.add(vehicle['id'])

            print('fo w2 vehicle', vehicle)

        for wid, w in self.work_dict.items():

            # 이미 delivery가 완료된 주문은 처리하지 않는다
            if wid in self.wave_1_done_deliveries:
                continue

            has_pickup, has_delivery, has_shipment = False, False, False
            assembly_job = False

            # wave 1 handle_pickup 주문 처리
            if w.status.type == WorkStatusType.handle_pickup:
                vid = w.status.vehicle_id

                pickup_skills = self.skills.get_task_skills_wave_vehicles([(1, vid)])

                has_pickup, has_delivery = True, False

                if w.pickup.group == w.delivery.group:
                    shipment_skills = pickup_skills

                    has_shipment = True

            # wave 1 handle_delivery 주문 처리
            elif w.status.type == WorkStatusType.handle_delivery:
                vid = w.status.vehicle_id

                delivery_skills = self.skills.get_task_skills_wave_vehicles([(1, vid)])

                has_pickup, has_delivery = False, True

            # assembly에 포함되어 있는 주문 처리
            elif w.status.type == WorkStatusType.assembly:
                assembly_id = w.status.assembly_id

                pickup_skills = self.skills.get_task_skills_assembly_visits(
                    w,
                    [(1, 's', assembly_id)],
                    True, False,
                )

                has_pickup, has_delivery = True, False
                assembly_job = True

                if w.pickup.group == w.delivery.group:
                    shipment_skills = pickup_skills

                    has_shipment = True

            # 이미 pickup을 완료한 주문 처리
            elif wid in self.wave_1_done_pickups:

                vid = self.wave_1_done_pickups[wid]

                # delivery: 지금 싣고있는 차량 및 만나는 차량이 처리 가능하다
                delivery_skills = self.skills.get_task_skills_meet_shipped_vehicle(
                    w, 1, vid, True,
                )

                has_pickup, has_delivery = False, True

            else:
                pickup_skills = self.skills.get_task_skills_waiting_pickup(w)

                has_pickup, has_delivery = True, False

                if w.pickup.group == w.delivery.group:
                    shipment_skills = self.skills.get_task_skills_waiting_shipment(w)

                    has_shipment = True

            # Create Jobs

            if has_pickup:

                # First Optimization은 pickup 우선처리, 모든 pickup 필수 처리
                pickup_job = {
                    'id': self.work_handler.pickup_index(wid),
                    'description': f'pickup-{w.description}',
                    'location': w.pickup.location,
                    'setup': w.pickup.setup_time,
                    'service': w.pickup.service_time,
                    'priority': PRIORITY_HIGHEST,
                    'skills': pickup_skills,
                }

                if w.amount is not None:
                    pickup_job['pickup'] = w.amount

                # assembly 주문은 이미 실려있으므로 setup, service time 미적용
                if assembly_job:
                    assembly_id = w.status.assembly_id

                    pickup_job['location'] = self.assembly_dict[assembly_id].location
                    pickup_job['setup'] = 0
                    pickup_job['service'] = 0

                fo_jobs.append(pickup_job)
                fo_must_handle_ids.add(pickup_job['id'])
                print('fo', 'p', wid, pickup_job)

            if has_delivery:

                # First Optimization은 delivery optional
                delivery_job = {
                    'id': self.work_handler.delivery_index(wid),
                    'description': f'delivery-{w.description}',
                    'location': w.delivery.location,
                    'setup': w.delivery.setup_time,
                    'service': w.delivery.service_time,
                    'skills': delivery_skills,
                }

                if w.amount is not None:
                    delivery_job['delivery'] = w.amount

                # must handle handle_delivery
                if w.status.type == WorkStatusType.handle_delivery:
                    delivery_job['priority'] = PRIORITY_HIGHEST
                    fo_must_handle_ids.add(delivery_job['id'])

                fo_jobs.append(delivery_job)
                print('fo', 'd', wid, delivery_job)

            if has_shipment:

                shipment = {
                    'pickup': {
                        'id': self.work_handler.shipment_pickup_index(wid),
                        'description': f'pickup-{w.description}',
                        'location': w.pickup.location,
                        'setup': w.pickup.setup_time,
                        'service': 0,
                    },
                    'delivery': {
                        'id': self.work_handler.shipment_delivery_index(wid),
                        'description': f'delivery-{w.description}',
                        'location': w.delivery.location,
                        'setup': w.delivery.setup_time,
                        'service': w.delivery.service_time,
                    },
                    'skills': shipment_skills,
                }

                if w.amount is not None:
                    shipment['amount'] = w.amount

                # assembly 주문은 이미 실려있으므로 setup, service time 미적용
                if assembly_job:
                    assembly_id = w.status.assembly_id

                    shipment['pickup']['location'] = self.assembly_dict[assembly_id].location
                    shipment['pickup']['setup'] = 0
                    shipment['pickup']['service'] = 0

                fo_shipments.append(shipment)
                print('fo', 's', wid, shipment)

        fo_request = {
            'jobs': fo_jobs,
            'shipments': fo_shipments,
            'vehicles': fo_vehicles,
            'distribute_options': {
                'max_vehicle_work_time': 86400,
                'custom_matrix': {
                    'enabled': True
                }
            }
        }

        fo_response = await self.minimum_end_time(fo_request, self.waves.w2.start_time, fo_minimum_time_vehicles, fo_must_handle_ids)

        # 반드시 포함되어야 하는 주문이 미배차된 경우
        # 기존에 배차되었던 task들의 pickup을 그대로 적용
        if any([u['id'] in fo_must_handle_ids for u in fo_response['unassigned']]):

            if self.waves.w2.assembly_stopover_times is None:
                raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail='assembly_stopover_time is required on wave 1 ended')

            for vs in self.waves.w1.vehicles:
                for t in vs.tasks:
                    if t.type == TaskType.pickup:
                        self.wave_1_pickups[t.work_id] = vs.id

            for vs in self.waves.w2.vehicles:
                for t in vs.tasks:
                    if t.type == TaskType.pickup:
                        self.wave_2_pickups[t.work_id] = vs.id

            self.wave_2_stopover_times = self.waves.w2.assembly_stopover_times

        else:

            for v in fo_response['routes']:
                v_idx = v['vehicle']
                w, vid = self.waves.vehicle_index_to_id(v_idx)
                wave = self.waves.w1 if w == 1 else self.waves.w2
                vehicle_schedule = wave.vehicles_dict[vid]
                assembly = self.assembly_dict[vehicle_schedule.to_assembly_id]

                for s in v['steps']:
                    if s['type'] == 'job':
                        if self.work_handler.is_dummy(s['id']):
                            continue

                        p, wid = self.work_handler.work_id(s['id'])
                        if p in ['pickup', 'shipment_pickup']:
                            if w == 1:
                                self.wave_1_pickups[wid] = vid
                            else:
                                self.wave_2_pickups[wid] = vid

                    elif s['type'] == 'end' and w == 2:
                        arrival = s['arrival']
                        print(f'v{v_idx} arrives {assembly.id} at {arrival}')
                        if (assembly.id not in self.wave_2_stopover_times) or (self.wave_2_stopover_times[assembly.id] < arrival):
                            self.wave_2_stopover_times[assembly.id] = arrival

                for s in v['steps']:
                    if s['type'] == 'pickup':
                        if self.work_handler.is_dummy(s['id']):
                            continue

                        _, wid = self.work_handler.work_id(s['id'])
                        if w == 1 and wid in self.wave_1_pickups and self.wave_1_pickups[wid] == vid:
                            self.wave_1_shipments[wid] = vid
                        elif w == 2 and wid in self.wave_2_pickups and self.wave_2_pickups[wid] == vid:
                            self.wave_2_shipments[wid] = vid

        # DEBUG
        # with open('/data/logs/roouty-dynamic-engine/fo_response.json', 'w') as f:
        #     json.dump(fo_response, f, ensure_ascii=False)

        # wave 2 집결시간이 존재하지 않는 경우 시작 + 3시간으로 고정 적용
        for aid, a in self.assembly_dict.items():
            if aid not in self.wave_2_stopover_times:
                self.wave_2_stopover_times[aid] = self.waves.w2.start_time + 10800

        print('w1-d-p', self.wave_1_done_pickups)
        print('w1-d-d', self.wave_1_done_deliveries)
        print('w1-p', self.wave_1_pickups)
        print('w1-sm', self.wave_1_shipments)
        print('s12-d', self.swap_1_2_down)
        print('s12-u', self.swap_1_2_up)
        print('w2-p', self.wave_2_pickups)
        print('w2-sm', self.wave_2_shipments)
        print('w2-sot', self.wave_2_stopover_times)

    async def second_optimization(self, request: Request, stopover_time: dict[int, int]):

        so_vehicles = []
        so_jobs = []
        so_shipments = []

        so_minimum_time_vehicles: set[int] = set()
        so_must_handle_ids: set[int] = set()

        if request.current_status in [CurrentStatus.wait, CurrentStatus.wave_1]:

            for vs in self.waves.w1.vehicles:
                v = self.vehicle_dict[vs.id]

                next_task = vs.first_undone_task()

                running = vs.running if next_task is not None else False

                start = v.location
                if request.current_status == CurrentStatus.wait:
                    assembly = self.assembly_dict[vs.from_assembly_id]
                    start = assembly.location
                elif request.current_status == CurrentStatus.wave_1:
                    if running:
                        start = next_task.location

                vehicle = {
                    'id': self.waves.w1.vehicle_id_to_index(vs.id),
                    'profile': v.profile.value,
                    'start': start,
                    'end': self.assembly_dict[vs.to_assembly_id].location,
                    'skills': self.skills.get_vehicle_skills(1, vs),
                    'wave': 1,
                }

                if v.capacity is not None:
                    vehicle['capacity'] = v.capacity

                # wave 1 차량은 업무시간 wave 1 start ~ wave 1 end
                tw_start = self.waves.w1.start_time
                tw_end = self.waves.w1.end_time

                if request.current_status == CurrentStatus.wave_1:
                    if running:
                        tw_start = next_task.eta
                        if tw_start < request.current_time:
                            tw_start = request.current_time
                    else:
                        tw_start = request.current_time

                # 실시간 스케줄 등의 이슈로 시간이 오버된 경우 최적화에서 제외
                # -> 하던 일만 하고 집결
                if tw_start < tw_end:
                    vehicle['time_window'] = (tw_start, tw_end)
                    so_vehicles.append(vehicle)
                    print('so w1 vehicle', vehicle)

        for vs in self.waves.w2.vehicles:
            v = self.vehicle_dict[vs.id]

            vehicle = {
                'id': self.waves.w2.vehicle_id_to_index(vs.id),
                'profile': v.profile.value,
                'start': self.assembly_dict[vs.from_assembly_id].location,
                'end': self.assembly_dict[vs.to_assembly_id].location,
                'skills': self.skills.get_vehicle_skills(2, vs),
                'wave': 2,
            }

            if v.capacity is not None:
                vehicle['capacity'] = v.capacity

            tw_start = self.waves.w2.start_time
            tw_end = tw_start + 86400

            # wave 2 차량은 업무시간 wave 2 start ~ wave_2_stopover_time
            if vs.to_assembly_id in stopover_time:
                # 정해진 시간에 딱 맞추면 미배차 발생하는 경우 다수 있음 -> 10분 term 추가
                tw_end = stopover_time[vs.to_assembly_id] + 600
            # stopover_time이 없으면 균등분배로 추가
            else:
                so_minimum_time_vehicles.add(vehicle['id'])

            vehicle['time_window'] = (tw_start, tw_end)
            so_vehicles.append(vehicle)
            print('so w2 vehicle', vehicle)

        for vs in self.waves.w3.vehicles:
            v = self.vehicle_dict[vs.id]

            vehicle = {
                'id': self.waves.w3.vehicle_id_to_index(vs.id),
                'profile': v.profile.value,
                'start': self.assembly_dict[vs.from_assembly_id].location,
                'skills': self.skills.get_vehicle_skills(3, vs),
                'wave': 3,
            }

            if v.capacity is not None:
                vehicle['capacity'] = v.capacity

            # wave 3 차량은 업무시간 wave_2_stopover_time + w3.stopover_waiting_time
            if vs.from_assembly_id in stopover_time:
                tw_start = stopover_time[vs.from_assembly_id] + self.waves.w3.stopover_waiting_time
                tw_end = tw_start + 86400

                vehicle['time_window'] = (tw_start, tw_end)

                so_vehicles.append(vehicle)
                so_minimum_time_vehicles.add(vehicle['id'])
                print('so w3 vehicle', vehicle)
            # stopover_time이 없으면 차량 미사용

        # status in [wait, wave_1]일 때에는 주문 상태와 권역,
        # 도착 집결지 위치에 맞게 설정한다
        if request.current_status in [CurrentStatus.wait, CurrentStatus.wave_1]:

            for wid, w in self.work_dict.items():

                # 이미 delivery가 완료된 주문은 처리하지 않는다
                if wid in self.wave_1_done_deliveries:
                    continue

                has_pickup, has_delivery, has_shipment = False, False, False
                assembly_job = False

                # assembly에 포함되어 있는 주문 처리
                if w.status.type == WorkStatusType.assembly:
                    assembly_job = True

                # wave 1 handle_pickup 주문은 wave_1_pickups에서 처리됨
                # wave 1 handle_delivery 주문 처리
                if w.status.type == WorkStatusType.handle_delivery:
                    vid = w.status.vehicle_id

                    delivery_skills = self.skills.get_task_skills_wave_vehicles([(1, vid)])

                    has_pickup, has_delivery, has_shipment = False, True, False

                # 이미 pickup을 완료한 주문 처리
                elif wid in self.wave_1_done_pickups:

                    vid = self.wave_1_done_pickups[wid]

                    # delivery: 지금 싣고있는 차량 및 만나는 차량이 처리 가능하다
                    delivery_skills = self.skills.get_task_skills_meet_shipped_vehicle(
                        w, 1, vid, True,
                    )

                    has_pickup, has_delivery, has_shipment = False, True, False

                # First Optimization에서 wave_1에 pickup을 처리하는 것으로 결정된 주문 처리
                elif wid in self.wave_1_pickups:

                    vid = self.wave_1_pickups[wid]

                    if wid not in self.wave_1_shipments:

                        # pickup: 지금 싣고있는 차량이 wave_1에서 처리 가능하다
                        pickup_skills = self.skills.get_task_skills_wave_vehicles([(1, vid)])

                        # delivery: 지금 싣고있는 차량이 만나는 차량이 처리 가능하다
                        # (자신은 처리 불가)
                        delivery_skills = self.skills.get_task_skills_meet_shipped_vehicle(
                            w, 1, vid, False,
                        )

                        has_pickup, has_delivery, has_shipment = True, True, False

                    else:

                        # shipment: 지금 싣고있는 차량이 wave_1에서 처리 가능하다
                        shipment_skills = self.skills.get_task_skills_wave_vehicles([(1, vid)])

                        has_pickup, has_delivery, has_shipment = False, False, True

                # First Optimization에서 wave_2에 pickup을 처리하는 것으로 결정된 주문 처리
                elif wid in self.wave_2_pickups:

                    vid = self.wave_2_pickups[wid]

                    if wid not in self.wave_2_shipments:

                        # pickup: 지금 싣고있는 차량이 wave_2에서 처리 가능하다
                        pickup_skills = self.skills.get_task_skills_wave_vehicles([(2, vid)])

                        # delivery: 지금 싣고있는 차량이 만나는 차량이 처리 가능하다
                        # (자신은 처리 불가)
                        delivery_skills = self.skills.get_task_skills_meet_shipped_vehicle(
                            w, 2, vid, False,
                        )

                        has_pickup, has_delivery, has_shipment = True, True, False

                    else:

                        # shipment: 지금 싣고있는 차량이 wave_2에서 처리 가능하다
                        shipment_skills = self.skills.get_task_skills_wave_vehicles([(2, vid)])

                        has_pickup, has_delivery, has_shipment = False, False, True

                # Create Jobs

                if has_pickup:

                    pickup_job = {
                        'id': self.work_handler.pickup_index(wid),
                        'description': f'pickup-{w.description}',
                        'location': w.pickup.location,
                        'setup': w.pickup.setup_time,
                        'service': w.pickup.service_time,
                        'skills': pickup_skills,
                    }

                    if w.amount is not None:
                        pickup_job['pickup'] = w.amount

                    # assembly 주문은 이미 실려있으므로 setup, service time 미적용
                    if assembly_job:
                        assembly_id = w.status.assembly_id

                        pickup_job['location'] = self.assembly_dict[assembly_id].location
                        pickup_job['setup'] = 0
                        pickup_job['service'] = 0

                    so_jobs.append(pickup_job)
                    so_must_handle_ids.add(pickup_job['id'])
                    print('so', 'p', wid, pickup_job)

                if has_delivery:

                    delivery_job = {
                        'id': self.work_handler.delivery_index(wid),
                        'description': f'delivery-{w.description}',
                        'location': w.delivery.location,
                        'setup': w.delivery.setup_time,
                        'service': w.delivery.service_time,
                        'skills': delivery_skills,
                    }

                    if w.amount is not None:
                        delivery_job['delivery'] = w.amount

                    so_jobs.append(delivery_job)
                    so_must_handle_ids.add(delivery_job['id'])
                    print('so', 'd', wid, delivery_job)

                if has_shipment:

                    shipment = {
                        'pickup': {
                            'id': self.work_handler.shipment_pickup_index(wid),
                            'description': f'pickup-{w.description}',
                            'location': w.pickup.location,
                            'setup': w.pickup.setup_time,
                            'service': w.pickup.service_time,
                        },
                        'delivery': {
                            'id': self.work_handler.shipment_delivery_index(wid),
                            'description': f'delivery-{w.description}',
                            'location': w.delivery.location,
                            'setup': w.delivery.setup_time,
                            'service': w.delivery.service_time,
                        },
                        'skills': shipment_skills,
                    }

                    if w.amount is not None:
                        shipment['amount'] = w.amount

                    # assembly 주문은 이미 실려있으므로 setup, service time 미적용
                    if assembly_job:
                        assembly_id = w.status.assembly_id

                        shipment['pickup']['location'] = self.assembly_dict[assembly_id].location
                        shipment['pickup']['setup'] = 0
                        shipment['pickup']['service'] = 0

                    so_shipments.append(shipment)
                    so_must_handle_ids.add(shipment['pickup']['id'])
                    so_must_handle_ids.add(shipment['delivery']['id'])
                    print('so', 's', wid, shipment)

        # status in [stopover]일 때에는 swap_1_2의 up, down을 고정한다
        elif request.current_status in [CurrentStatus.stopover]:

            for wid, w in self.work_dict.items():

                # 이미 delivery가 완료된 주문은 처리하지 않는다
                if wid in self.wave_1_done_deliveries:
                    continue

                has_pickup, has_delivery, has_shipment = False, False, False

                # wave 1 handle_delivery 주문 처리
                if w.status.type == WorkStatusType.handle_delivery:
                    vid = w.status.vehicle_id

                    delivery_skills = self.skills.get_task_skills_wave_vehicles([(1, vid)])

                    has_pickup, has_delivery, has_shipment = False, True, False

                # 이미 pickup을 완료한 주문 처리
                elif wid in self.wave_1_done_pickups:

                    vid = self.wave_1_done_pickups[wid]

                    # delivery:

                    # swap_1_2에서 내린 주문은 이 때 pickup한 차량이
                    # wave_2 or wave_3에서 배송해야 한다
                    if wid in self.swap_1_2_down:
                        upvid = self.swap_1_2_up[wid]
                        delivery_skills = self.skills.get_task_skills_wave_vehicles(
                            [(2, upvid), (3, upvid)])

                    # swap_2_3에서 내린 주문은 이 때 pickup한 차량이
                    # wave_3에서 배송해야 한다
                    elif wid in self.swap_2_3_down:
                        upvid = self.swap_2_3_up[wid]
                        delivery_skills = self.skills.get_task_skills_wave_vehicles(
                            [(3, upvid)])

                    # 내린적이 없는 주문은 싣고 있는 차량이
                    # wave_2 or wave_3에서 배송해야 한다
                    else:
                        delivery_skills = self.skills.get_task_skills_wave_vehicles(
                            [(2, vid), (3, vid)])

                    has_pickup, has_delivery, has_shipment = False, True, False

                # First Optimization에서 wave_2에 pickup을 처리하는 것으로 결정된 주문 처리
                elif wid in self.wave_2_pickups:

                    vid = self.wave_2_pickups[wid]
                    vs2 = self.waves.w2.vehicles_dict[vid]

                    if wid not in self.wave_2_shipments:

                        # pickup: 지금 싣고있는 차량이 wave_2에서 처리 가능하다
                        pickup_skills = self.skills.get_task_skills_wave_vehicles(
                            [(2, vid)])

                        # delivery: 지금 싣고있는 차량이 만나는 차량이 처리 가능하다
                        # (자신은 처리 불가)
                        delivery_skills = self.skills.get_task_skills_meet_shipped_vehicle(
                            w, 2, vid, False,
                        )

                        has_pickup, has_delivery, has_shipment = True, True, False

                    else:

                        # shipment: 지금 싣고있는 차량이 wave_2에서 처리 가능하다
                        shipment_skills = self.skills.get_task_skills_wave_vehicles(
                            [(2, vid)])

                        has_pickup, has_delivery, has_shipment = False, False, True

                # Create Jobs

                if has_pickup:

                    pickup_job = {
                        'id': self.work_handler.pickup_index(wid),
                        'description': f'pickup-{w.description}',
                        'location': w.pickup.location,
                        'setup': w.pickup.setup_time,
                        'service': w.pickup.service_time,
                        'skills': pickup_skills,
                    }

                    if w.amount is not None:
                        pickup_job['pickup'] = w.amount

                    so_jobs.append(pickup_job)
                    so_must_handle_ids.add(pickup_job['id'])
                    print('so', 'p', wid, pickup_job)

                if has_delivery:

                    delivery_job = {
                        'id': self.work_handler.delivery_index(wid),
                        'description': f'delivery-{w.description}',
                        'location': w.delivery.location,
                        'setup': w.delivery.setup_time,
                        'service': w.delivery.service_time,
                        'skills': delivery_skills,
                    }

                    if w.amount is not None:
                        delivery_job['delivery'] = w.amount

                    so_jobs.append(delivery_job)
                    so_must_handle_ids.add(delivery_job['id'])
                    print('so', 'd', wid, delivery_job)

                if has_shipment:

                    shipment = {
                        'pickup': {
                            'id': self.work_handler.shipment_pickup_index(wid),
                            'description': f'pickup-{w.description}',
                            'location': w.pickup.location,
                            'setup': w.pickup.setup_time,
                            'service': w.pickup.service_time,
                        },
                        'delivery': {
                            'id': self.work_handler.shipment_delivery_index(wid),
                            'description': f'delivery-{w.description}',
                            'location': w.delivery.location,
                            'setup': w.delivery.setup_time,
                            'service': w.delivery.service_time,
                        },
                        'skills': shipment_skills,
                    }

                    if w.amount is not None:
                        shipment['amount'] = w.amount

                    # assembly 주문은 이미 실려있으므로 setup, service time 미적용
                    if assembly_job:
                        assembly_id = w.status.assembly_id

                        shipment['pickup']['location'] = self.assembly_dict[assembly_id].location
                        shipment['pickup']['setup'] = 0
                        shipment['pickup']['service'] = 0

                    so_shipments.append(shipment)
                    so_must_handle_ids.add(shipment['pickup']['id'])
                    so_must_handle_ids.add(shipment['delivery']['id'])
                    print('so', 's', wid, shipment)

        # TODO
        else:
            raise HTTPException(400, f'request.current_status={request.current_status} not supported yet.')

        so_request = {
            'jobs': so_jobs,
            'shipments': so_shipments,
            'vehicles': so_vehicles,
            'distribute_options': {
                'max_vehicle_work_time': 86400,
                'custom_matrix': {
                    'enabled': True
                }
            }
        }

        # print(json.dumps(so_request, ensure_ascii=False))

        return await self.minimum_end_time(so_request, self.waves.w2.start_time, so_minimum_time_vehicles, so_must_handle_ids)

    async def make_response(self, request: Request, response: dict, stopover_time: dict[int, int]) -> Response:

        routes_dict = { v['vehicle']: v for v in response['routes'] }

        wave_1_dict: dict[int, VehicleTasks] = {}
        swap_1_2_dict: dict[int, VehicleSwaps] = {}
        wave_2_dict: dict[int, VehicleTasks] = {}
        swap_2_3_dict: dict[int, VehicleSwaps] = {}
        wave_3_dict: dict[int, VehicleTasks] = {}

        # work_id: [vehicle_id, assembly_id]
        wave_1_p: dict[int, tuple[int, int]] = {}
        wave_2_p: dict[int, tuple[int, int]] = {}
        wave_2_d: dict[int, tuple[int, int]] = {}
        wave_3_d: dict[int, tuple[int, int]] = {}

        for vs in self.waves.w1.vehicles:
            v = self.vehicle_dict[vs.id]

            swap_1_2_dict[vs.id] = VehicleSwaps(
                vehicle_id=vs.id,
                assembly_id=vs.to_assembly_id,
                stopover_time=self.waves.w1.end_time,
                down=[],
                up=[],
            )

            tasks: list[Task] = []

            vehicle_index = self.waves.w1.vehicle_id_to_index(vs.id)

            departure_done = False

            for t in vs.tasks:
                if not t.done:
                    break

                task = Task(
                    work_id=t.work_id,
                    type=t.type,
                    eta=t.eta,
                    setup_time=t.setup_time,
                    service_time=t.service_time,
                    assembly_id=t.assembly_id,
                    location=t.location,
                    done=t.done,
                )

                if t.done:
                    departure_done = True

                if t.type == TaskType.departure:
                    task.assembly_id = vs.from_assembly_id

                if t.type == TaskType.arrival:
                    task.assembly_id = vs.to_assembly_id

                tasks.append(task)

            if vehicle_index in routes_dict:

                routes = routes_dict[vehicle_index]

                for step in routes['steps']:
                    eta = step['arrival']
                    setup_time = step['setup']
                    service_time = step['service']
                    location = (step['location'][0], step['location'][1])

                    if step['type'] in ['job', 'pickup', 'delivery']:
                        p, wid = self.work_handler.work_id(step['id'])
                        if p in ['pickup', 'shipment_pickup']:
                            done = self.work_dict[wid].status.type == WorkStatusType.assembly
                            tasks.append(Task(
                                work_id=wid,
                                type=TaskType.pickup,
                                eta=eta,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=None,
                                location=location,
                                done=done,
                            ))
                            if done:
                                departure_done = True

                        elif p in ['delivery', 'shipment_delivery']:
                            tasks.append(Task(
                                work_id=wid,
                                type=TaskType.delivery,
                                eta=eta,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=None,
                                location=location,
                            ))

            else:

                running = False
                next_task = None
                handling_work = None

                if request.current_status == CurrentStatus.wave_1:
                    next_task = vs.first_undone_task()
                    running = vs.running if next_task is not None else False
                    if running and next_task.work_id is not None:
                        handling_work = self.work_dict[next_task.work_id]

                if handling_work is not None and handling_work.status.type == WorkStatusType.handle_pickup:
                    tasks.append(Task(
                        work_id=handling_work.id,
                        type=TaskType.pickup,
                        eta=next_task.eta,
                        setup_time=handling_work.pickup.setup_time,
                        service_time=handling_work.pickup.service_time,
                        assembly_id=None,
                        location=handling_work.pickup.location,
                    ))

                elif handling_work is not None and handling_work.status.type == WorkStatusType.handle_delivery:
                    tasks.append(Task(
                        work_id=handling_work.id,
                        type=TaskType.delivery,
                        eta=next_task.eta,
                        setup_time=handling_work.delivery.setup_time,
                        service_time=handling_work.delivery.service_time,
                        assembly_id=None,
                        location=handling_work.delivery.location,
                    ))

            from_assembly = self.assembly_dict[vs.from_assembly_id]
            to_assembly = self.assembly_dict[vs.to_assembly_id]

            if len(tasks) == 0 or tasks[0].type != TaskType.departure:
                tasks.insert(0, Task(
                    work_id=None,
                    type=TaskType.departure,
                    eta=self.waves.w1.start_time,
                    assembly_id=from_assembly.id,
                    location=from_assembly.location,
                    done=(departure_done) or (vs.id in self.wave_1_departed),
                ))

            if tasks[-1].type != TaskType.arrival:
                tasks.append(Task(
                    work_id=None,
                    type=TaskType.arrival,
                    eta=self.waves.w1.end_time,
                    assembly_id=to_assembly.id,
                    location=to_assembly.location,
                    done=vs.id in self.wave_1_arrived,
                ))

            pickup_set: set[int] = set()

            for t in tasks:
                if t.type == TaskType.pickup:
                    pickup_set.add(t.work_id)

            for wid in pickup_set:
                wave_1_p[wid] = (vs.id, vs.to_assembly_id)

            await self.setup_route_data_for_tasks(v.profile.value, tasks)

            wave_1_dict[vs.id] = VehicleTasks(
                vehicle_id=vs.id,
                tasks=tasks,
            )

        for vs in self.waves.w2.vehicles:
            v = self.vehicle_dict[vs.id]

            swap_2_3_dict[vs.id] = VehicleSwaps(
                vehicle_id=vs.id,
                assembly_id=vs.to_assembly_id,
                stopover_time=stopover_time[vs.to_assembly_id],
                down=[],
                up=[],
            )

            tasks: list[Task] = []

            vehicle_index = self.waves.w2.vehicle_id_to_index(vs.id)

            if vehicle_index in routes_dict:

                routes = routes_dict[vehicle_index]

                for step in routes['steps']:
                    eta = step['arrival']
                    setup_time = step['setup']
                    service_time = step['service']
                    location = (step['location'][0], step['location'][1])

                    if step['type'] == 'start':
                        tasks.append(Task(
                            work_id=None,
                            type=TaskType.departure,
                            eta=eta,
                            setup_time=setup_time,
                            service_time=service_time,
                            assembly_id=vs.from_assembly_id,
                            location=location,
                        ))

                    if step['type'] in ['job', 'pickup', 'delivery']:
                        p, wid = self.work_handler.work_id(step['id'])
                        if p in ['pickup', 'shipment_pickup']:
                            tasks.append(Task(
                                work_id=wid,
                                type=TaskType.pickup,
                                eta=eta,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=None,
                                location=location,
                            ))
                        elif p in ['delivery', 'shipment_delivery']:
                            tasks.append(Task(
                                work_id=wid,
                                type=TaskType.delivery,
                                eta=eta,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=None,
                                location=location,
                            ))

                    elif step['type'] == 'end':
                        tasks.append(Task(
                            work_id=None,
                            type=TaskType.arrival,
                            eta=eta,
                            setup_time=setup_time,
                            service_time=service_time,
                            assembly_id=vs.to_assembly_id,
                            location=location,
                        ))

            from_assembly = self.assembly_dict[vs.from_assembly_id]
            to_assembly = self.assembly_dict[vs.to_assembly_id]

            if len(tasks) == 0:
                tasks.append(Task(
                    work_id=None,
                    type=TaskType.departure,
                    eta=self.waves.w2.start_time,
                    assembly_id=from_assembly.id,
                    location=from_assembly.location,
                ))

            if tasks[-1].type != TaskType.arrival:
                tasks.append(Task(
                    work_id=None,
                    type=TaskType.arrival,
                    eta=stopover_time[to_assembly.id],
                    assembly_id=to_assembly.id,
                    location=to_assembly.location,
                ))

            pickup_set: set[int] = set()
            delivery_set: set[int] = set()

            for t in tasks:
                if t.type == TaskType.pickup:
                    pickup_set.add(t.work_id)
                elif t.type == TaskType.delivery:
                    delivery_set.add(t.work_id)

            for wid in pickup_set:
                wave_2_p[wid] = (vs.id, vs.to_assembly_id)

            for wid in delivery_set:
                wave_2_d[wid] = (vs.id, vs.from_assembly_id)

            await self.setup_route_data_for_tasks(v.profile.value, tasks)

            wave_2_dict[vs.id] = VehicleTasks(
                vehicle_id=vs.id,
                tasks=tasks,
            )

        for vs in self.waves.w3.vehicles:
            v = self.vehicle_dict[vs.id]

            tasks: list[Task] = []

            vehicle_index = self.waves.w3.vehicle_id_to_index(vs.id)

            if vehicle_index in routes_dict:

                routes = routes_dict[vehicle_index]

                for step in routes['steps']:
                    eta = step['arrival']
                    setup_time = step['setup']
                    service_time = step['service']
                    location = (step['location'][0], step['location'][1])

                    if step['type'] == 'start':
                        tasks.append(Task(
                            work_id=None,
                            type=TaskType.departure,
                            eta=eta,
                            setup_time=setup_time,
                            service_time=service_time,
                            assembly_id=vs.from_assembly_id,
                            location=location,
                        ))

                    if step['type'] in ['job', 'pickup', 'delivery']:
                        p, wid = self.work_handler.work_id(step['id'])
                        if p in ['pickup', 'shipment_pickup']:
                            tasks.append(Task(
                                work_id=wid,
                                type=TaskType.pickup,
                                eta=eta,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=None,
                                location=location,
                            ))
                        elif p in ['delivery', 'shipment_delivery']:
                            tasks.append(Task(
                                work_id=wid,
                                type=TaskType.delivery,
                                eta=eta,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=None,
                                location=location,
                            ))

                    elif step['type'] == 'end':
                        tasks.append(Task(
                            work_id=None,
                            type=TaskType.arrival,
                            eta=eta,
                            setup_time=setup_time,
                            service_time=service_time,
                            assembly_id=None,
                            location=location,
                        ))

            delivery_set: set[int] = set()

            for t in tasks:
                if t.type == TaskType.delivery:
                    delivery_set.add(t.work_id)

            for wid in delivery_set:
                wave_3_d[wid] = (vs.id, vs.from_assembly_id)

            await self.setup_route_data_for_tasks(v.profile.value, tasks)

            wave_3_dict[vs.id] = VehicleTasks(
                vehicle_id=vs.id,
                tasks=tasks,
            )

        print('wave_1_p', wave_1_p)
        print('wave_2_p', wave_2_p)
        print('wave_2_d', wave_2_d)
        print('wave_3_d', wave_3_d)

        for wid, w in self.work_dict.items():

            # wave_1에서 pickup 된 주문
            if wid in wave_1_p:
                v1, a1 = wave_1_p[wid]

                # wave_1에서 delivery 된 경우
                # 동일 차량으로 처리되므로 not considered in swap

                # wave_2에서 delivery 된 경우
                if wid in wave_2_d:
                    v2, a2 = wave_2_d[wid]

                    # pickup 차량과 delivery 차량이 다른 경우
                    if v1 != v2:
                        # pickup 차량의 도착 위치와 delivery 차량의 출발 위치가 다르면 에러
                        if a1 != a2:
                            raise HTTPException(
                                500,
                                f'work {wid} down at {a1} by {v1}, but up at {a2} by {v2}',
                            )

                        # 1_2 에서 만나서 교환
                        swap_1_2_dict[v1].down.append(wid)
                        swap_1_2_dict[v2].up.append(wid)

                # wave_3에서 delivery 된 경우
                elif wid in wave_3_d:
                    v3, a3 = wave_3_d[wid]

                    # pickup 차량과 delivery 차량이 다른 경우
                    if v1 != v3:
                        vs1_2 = self.waves.w2.vehicles_dict[v1]
                        vs3_2 = self.waves.w2.vehicles_dict[v3]

                        # pickup 차량이 wave_1에 도착한 집결지와
                        # delivery 차량이 wave_2에 출발한 집결지가 같으면
                        # 1_2 에서 만나서 교환
                        if a1 == vs3_2.from_assembly_id:
                            swap_1_2_dict[v1].down.append(wid)
                            swap_1_2_dict[v3].up.append(wid)
                        # pickup 차량이 wave_2에 도착한 집결지와
                        # delivery 차량이 wave_3에 출발한 집결지가 같으면
                        # 2_3 에서 만나서 교환
                        elif vs1_2.to_assembly_id == a3:
                            swap_2_3_dict[v1].down.append(wid)
                            swap_2_3_dict[v3].up.append(wid)
                        # 만나는 집결지가 존재하지 않음
                        else:
                            raise HTTPException(
                                500,
                                f'work {wid} cannot match at ' +
                                f'1_2 (down at {a1} by {v1}, up at {vs3_2.from_assembly_id} by {v3}) and ' +
                                f'2_3 (down at {vs1_2.to_assembly_id} by {v1}, up at {a3} by {v3})',
                            )

            # wave_2에서 pickup 된 주문
            elif wid in wave_2_p:
                v2, a2 = wave_2_p[wid]

                # wave_2에서 delivery 된 경우
                # 동일 차량으로 처리되므로 not considered in swap

                # wave_3에서 delivery 된 경우
                if wid in wave_3_d:
                    v3, a3 = wave_3_d[wid]

                    # pickup 차량과 delivery 차량이 다른 경우
                    if v2 != v3:
                        # pickup 차량의 도착 위치와 delivery 차량의 출발 위치가 다르면 에러
                        if a2 != a3:
                            raise HTTPException(
                                500,
                                f'work {wid} down at {a2} by {v2}, but up at {a3} by {v3}',
                            )

                        # 2_3 에서 만나서 교환
                        swap_2_3_dict[v2].down.append(wid)
                        swap_2_3_dict[v3].up.append(wid)

        wave_1: list[VehicleTasks] = [ v for _, v in wave_1_dict.items() ]
        swap_1_2: list[VehicleSwaps] = [ v for _, v in swap_1_2_dict.items() ]
        wave_2: list[VehicleTasks] = [ v for _, v in wave_2_dict.items() ]
        swap_2_3: list[VehicleSwaps] = [ v for _, v in swap_2_3_dict.items() ]
        wave_3: list[VehicleTasks] = [ v for _, v in wave_3_dict.items() ]

        return Response(
            wave_1=wave_1,
            swap_1_2=swap_1_2,
            wave_2=wave_2,
            swap_2_3=swap_2_3,
            wave_3=wave_3,
        )
