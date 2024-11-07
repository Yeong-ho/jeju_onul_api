from fastapi import HTTPException
from http import HTTPStatus
import concurrent.futures
import json

from .transaction import *
from datetime import timedelta
import dependencies.vroouty as vroouty
import dependencies.osrm as osrm
import shapely.geometry as geometry
from collections import defaultdict

PRIORITY_MUST_HAVE_TO = 99
PRIORITY_HIGHEST = 40
PRIORITY_HIGH = 30
PRIORITY_MEDIUM = 20
PRIORITY_LOW = 10
PRIORITY_LOWEST = 0

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
    ) -> None:
        self.__unique_skill_id = 0
        self.__skills = {}
        self.__vehicles = [v.id for v in vehicles]
        self.__group_vehicles = {}
        self.__assembly_visits = {}

    def add_key(self, key: str):
        if key not in self.__skills:
            self.__skills[key] = self.__unique_skill_id
            self.__unique_skill_id += 1


class IdHandler:
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

    def pickup_index(self, work_id: str) -> int:
        return self.__setup_key(('pickup', work_id))

    def delivery_index(self, work_id: str) -> int:
        return self.__setup_key(('delivery', work_id))

    def shipment_pickup_index(self, work_id: str) -> int:
        return self.__setup_key(('shipment_pickup', work_id))

    def shipment_delivery_index(self, work_id: str) -> int:
        return self.__setup_key(('shipment_delivery', work_id))

    def shipment_assembly_index(self, work_id: str) -> int:
        return self.__setup_key(('shipment_assembly', work_id))

    def vehicle_index(self, vehicle_id: str) -> int:
        return self.__setup_key(('vehicle', vehicle_id))

    def dummy_index(self, vehicle_id: str) -> int:
        return self.__setup_key(('dummy', vehicle_id))

    def get_id(self, index: int) -> tuple[str, str]:
        return self.__index_to_id[index]

    def is_dummy(self, index: int) -> bool:
        return self.__index_to_id[index][0] in ['dummy', 'shipment_assembly']


class OptimizationHandler:
    # vehicle_dict: dict[str, Vehicle]
    # assembly_dict: dict[str, Assembly]
    # work_dict: dict[str, Work]

    # skills: Skills
    # id_handler: IdHandler

    def __init__(self, request: Request) -> None:
        self.vehicle_dict: dict[str, Vehicle]
        self.assembly_dict: dict[str, Assembly]
        self.work_dict: dict[str, Work]
        self.skills: Skills

        self.vehicle_dict = {v.id: v for v in request.vehicles}
        self.assembly_dict = {a.id: a for a in request.assemblies}
        self.work_dict = {w.id: w for w in request.works}
        self.polygon_dict = {p.id: geometry.Polygon(p.polygon) for p in request.boundaries}
        self.skills = Skills(request.vehicles, request.assemblies)
        self.id_handler = IdHandler()

        pickup_location_count = defaultdict(int)
        delivery_location_count = defaultdict(int)

        for _, work in self.work_dict.items():
            for group, polygon in self.polygon_dict.items():
                if polygon.contains(geometry.Point(work.pickup.location)):
                    work.pickup.group_id = group
                    break

            for group, polygon in self.polygon_dict.items():
                if polygon.contains(geometry.Point(work.delivery.location)):
                    work.delivery.group_id = group
                    break

            pickup_location_count[tuple(work.pickup.location)] += 1
            delivery_location_count[tuple(work.delivery.location)] += 1

        pickup_duplicated_locations = [location for location, count in pickup_location_count.items() if count >= 2]
        delivery_duplicated_locations = [location for location, count in delivery_location_count.items() if count >= 2]

        for _, work in self.work_dict.items():
            if tuple(work.pickup.location) in pickup_duplicated_locations: 
                work.pickup.setup_time=timedelta(seconds=300)
                work.pickup.service_time=timedelta(seconds=10)
                self.work_dict[work.id] = work
            else:
                work.pickup.setup_time=timedelta(seconds=180)
                work.pickup.service_time=timedelta(seconds=10)
                self.work_dict[work.id] = work

            if tuple(work.delivery.location) in delivery_duplicated_locations:
                work.delivery.setup_time=timedelta(seconds=300)
                work.delivery.service_time=timedelta(seconds=10)
                self.work_dict[work.id] = work
            else:
                work.delivery.setup_time=timedelta(seconds=180)
                work.delivery.service_time=timedelta(seconds=10)
                self.work_dict[work.id] = work

    async def process_opt_wave1(self):
        vehicle_groups = dict()
        vehicle_works: dict[str, list[Work]] = dict()
        vty_responses = dict()


        for vehicle_id, vehicle in self.vehicle_dict.items():
            vehicle_works[vehicle_id] = []
            for group_id in vehicle.include:
                vehicle_groups[group_id] = vehicle_id

        for _, work in self.work_dict.items():
            # 기사의 재량으로 제외권역 follow up
            if work.exception:
                if work.fix_vehicle_id is None:
                    raise HTTPException(422, "Not found fix_vehicle_id")
                vehicle_works[work.fix_vehicle_id].append(work)
                continue

            # 초기 권역에 포함되지 않은 주문 생략 
            if work.pickup.group_id not in vehicle_groups:
                continue
            handling_vehicle_id = vehicle_groups[work.pickup.group_id]
            vehicle_works[handling_vehicle_id].append(work)

        for _, vehicle in self.vehicle_dict.items():
            vty_jobs = []
            vty_shipments = []
            vty_vehicles = []

            for work in vehicle_works[vehicle.id]:
                # WorkStatus가 현재 pickup한 상태인경우 제외
                if work.status.type == WorkStatusType.waiting:
                    pickup_job = work.pickup.to_job(index=self.id_handler.pickup_index(work.id))
                    vty_jobs.append(pickup_job)

            vehicle_index = self.id_handler.vehicle_index(vehicle.id)
            vty_vehicle = {
                'id': vehicle_index,
                'profile': vehicle.profile.value,
                'start': vehicle.current_location,
            }
            vty_vehicles.append(vty_vehicle)

            if len(vty_jobs) == 0 and len(vty_shipments) == 0:
                continue

            vroouty_request = {
                'jobs': vty_jobs,
                'shipments': vty_shipments,
                'vehicles': vty_vehicles,
                'distribute_options': {
                    'custom_matrix': {
                        'enabled': True
                    }
                }
            }

            status, vty_response = await vroouty.Post(vroouty_request)

            # 각 차량 배차결과가 30분 이내에 완료될시 부권역과 delivery job 추가 후 재배차
            if 1800 > int(
                    next(step["arrival"] for step in vty_response["routes"][0]["steps"] if step["type"] == "end")):
                vty_jobs = []

                for work in vehicle_works[vehicle.id]:
                    if work.status.type == WorkStatusType.waiting and work.pickup.group_id in vehicle.exclude:
                        vty_jobs.append(work.pickup.to_job(index=self.id_handler.pickup_index(work.id)))
                    elif work.status.type == WorkStatusType.waiting:
                        if work.pickup.group_id in vehicle.include and work.delivery.group_id in vehicle.include:
                            pickup_job = work.pickup.to_job(index=self.id_handler.pickup_index(work.id))
                            delivery_job = work.delivery.to_job(index=self.id_handler.delivery_index(work.id))
                            vty_shipments.append(
                                {
                                    'pickup': pickup_job,
                                    'delivery': delivery_job
                                }
                            )
                            continue

                        pickup_job = work.pickup.to_job(index=self.id_handler.pickup_index(work.id))
                        vty_jobs.append(pickup_job)
                    elif work.status.type == WorkStatusType.shipped and work.delivery.group_id in vehicle.include:
                        vty_jobs.append(work.delivery.to_job(index=self.id_handler.delivery_index(work.id)))

                vroouty_request = {
                    'jobs': vty_jobs,
                    'shipments': vty_shipments,
                    'vehicles': vty_vehicles,
                    'distribute_options': {
                        'custom_matrix': {
                            'enabled': True
                        }
                    }
                }
                status, vty_response = await vroouty.Post(vroouty_request)

            if status != 200:
                raise HTTPException(500, vty_response)

            vty_responses[vehicle.id] = vty_response

        return vty_responses

    async def process_opt_wave2(self):
        vty_jobs = []
        vty_shipments = []
        vty_vehicles = []

        for _, work in self.work_dict.items():
            # WorkStatus가 현재 pickup한 상태인경우 제외
            if work.status.type == WorkStatusType.waiting:
                pickup_job = work.pickup.to_job(index=self.id_handler.pickup_index(work.id))
                vty_jobs.append(pickup_job)

        for _, vehicle in self.vehicle_dict.items():
            vty_vehicles.append({
                'id': self.id_handler.vehicle_index(vehicle.id),
                'profile': vehicle.profile.value,
                'start': vehicle.current_location,
                'end': next(iter(self.assembly_dict.values())).location
            })

        vroouty_request = {
            'jobs': vty_jobs,
            'shipments': vty_shipments,
            'vehicles': vty_vehicles,
            'distribute_options': {
                'equalize_work_time': {
                    'enabled': True
                },
                'custom_matrix': {
                    'enabled': True
                }
            }
        }

        status, vty_response = await vroouty.Post(vroouty_request)

        # import json
        # print(json.dumps(vty_response))

        if status != 200:
            raise HTTPException(500, vty_response)

        return vty_response

    async def process_opt_wave3(self):
        vty_jobs = []
        vty_shipments = []
        vty_vehicles = []

        for _, work in self.work_dict.items():
            if work.status.type == WorkStatusType.done:
                continue
            delivery_job = work.delivery.to_job(index=self.id_handler.delivery_index(work.id))
            vty_jobs.append(delivery_job)

        for _, vehicle in self.vehicle_dict.items():
            vty_vehicles.append({
                'id': self.id_handler.vehicle_index(vehicle.id),
                'profile': vehicle.profile.value,
                'start': next(iter(self.assembly_dict.values())).location
            })

        vroouty_request = {
            'jobs': vty_jobs,
            'shipments': vty_shipments,
            'vehicles': vty_vehicles,
            'distribute_options': {
                'equalize_work_time': {
                    'enabled': True
                },
                'custom_matrix': {
                    'enabled': True
                }
            }
        }
        status, vty_response = await vroouty.Post(vroouty_request)

        if status != 200:
            raise HTTPException(500, vty_response)
        
        return vty_response

    async def make_beforetask(self, vty_response: dict):
        vehicle_tasks: list[VehicleTasks] = []
        vehicles_assemble_time = []

        for vehicle in vty_response['routes']:
            vehicles_assemble_time.append(vehicle['steps'][-1]['arrival'])

        for vehicle in vty_response['routes']:
            step_list = []
            for step in vehicle['steps']:
                if step['type'] == 'job':
                    step_list.append(step['id'])
            
            if vehicle['steps'][-1]['arrival'] < max(vehicles_assemble_time):
                vty_jobs =[]
                vty_shipments = []
                vty_vehicles = []

                for _,work in self.work_dict.items():
                    if work.status.type == WorkStatusType.shipped and self.id_handler.get_id(vehicle['vehicle'])[1] == work.status.vehicle_id :
                        vty_jobs.append(work.delivery.to_job(index=self.id_handler.delivery_index(work.id)))
                    elif work.status.type == WorkStatusType.waiting and self.id_handler.pickup_index(work.id) in step_list:
                        pickup_job = work.pickup.to_job(index=self.id_handler.pickup_index(work.id))
                        pickup_job['priority']=1
                        vty_jobs.append(pickup_job)

                for _, vehicle_set in self.vehicle_dict.items():
                    if vehicle_set.id == self.id_handler.get_id(vehicle['vehicle'])[1] :
                        vty_vehicles.append({
                            'id': self.id_handler.vehicle_index(vehicle_set.id),
                            'profile': vehicle_set.profile.value,
                            'start': vehicle_set.current_location,
                            'end': next(iter(self.assembly_dict.values())).location
                        })
                        break

                vroouty_request = {
                    'jobs': vty_jobs,
                    'shipments': vty_shipments,
                    'vehicles': vty_vehicles,
                    'distribute_options': {
                        'max_vehicle_work_time': max(vehicles_assemble_time),
                        'custom_matrix': {
                            'enabled': True
                        }
                    }
                }
                status, response_modified = await vroouty.Post(vroouty_request)

                for vehicle_modified in response_modified['routes']:
                    tasks: list[Task] = []
                    for step in vehicle_modified['steps']:
                        eta = step['arrival']
                        duration = step['duration']
                        distance = step['distance']
                        setup_time = step['setup']
                        service_time = step['service']
                        location = (step['location'][0], step['location'][1])

                        if step['type'] in ['job', 'pickup', 'delivery']:
                            index_type, work_id = self.id_handler.get_id(step['id'])

                            if index_type in ['pickup', 'shipment_pickup']:
                                tasks.append(Task(
                                    work_id=work_id,
                                    type=TaskType.pickup,
                                    eta=eta,
                                    duration=duration,
                                    distance=distance,
                                    setup_time=setup_time,
                                    service_time=service_time,
                                    assembly_id=None,
                                    location=location,
                                ))

                            elif index_type in ['delivery', 'shipment_delivery']:
                                tasks.append(Task(
                                    work_id=work_id,
                                    type=TaskType.delivery,
                                    eta=eta,
                                    duration=duration,
                                    distance=distance,
                                    setup_time=setup_time,
                                    service_time=service_time,
                                    location=location,
                                ))
                        elif step['type'] in ['end']:
                            tasks.append(Task(
                                work_id=None,
                                type=TaskType.arrival,
                                eta=eta,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=next(iter(self.assembly_dict.values())).id,
                                location=location,
                            ))

                    _, vehicle_id = self.id_handler.get_id(vehicle_modified['vehicle'])
                    vehicle_tasks.append(VehicleTasks(
                        vehicle_id=vehicle_id,
                        tasks=tasks,
                    ))
            else :
                tasks: list[Task] = []
                for step in vehicle['steps']:
                    eta = step['arrival']
                    duration = step['duration']
                    distance = step['distance']
                    setup_time = step['setup']
                    service_time = step['service']
                    location = (step['location'][0], step['location'][1])

                    if step['type'] in ['job', 'pickup', 'delivery']:
                        index_type, work_id = self.id_handler.get_id(step['id'])

                        if index_type in ['pickup', 'shipment_pickup']:
                            tasks.append(Task(
                                work_id=work_id,
                                type=TaskType.pickup,
                                eta=eta,
                                duration=duration,
                                distance=distance,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=None,
                                location=location,
                            ))

                        elif index_type in ['delivery', 'shipment_delivery']:
                            tasks.append(Task(
                                work_id=work_id,
                                type=TaskType.delivery,
                                eta=eta,
                                duration=duration,
                                distance=distance,
                                setup_time=setup_time,
                                service_time=service_time,
                                location=location,
                            ))
                    elif step['type'] in ['end']:
                        tasks.append(Task(
                            work_id=None,
                            type=TaskType.arrival,
                            eta=eta,
                            setup_time=setup_time,
                            service_time=service_time,
                            assembly_id=next(iter(self.assembly_dict.values())).id,
                            location=location,
                        ))

                _, vehicle_id = self.id_handler.get_id(vehicle['vehicle'])
                vehicle_tasks.append(VehicleTasks(
                    vehicle_id=vehicle_id,
                    tasks=tasks,
                ))

        await self.beforetask_delivery_done(vehicle_tasks) 
        return vehicle_tasks

    async def beforetask_delivery_done(self, vehicles_tasks):
        #집결전 task에서 delivery된 work status done 처리
        done_worklist = []
        for vehicle_tasks in vehicles_tasks:
            for task in vehicle_tasks.tasks:
                if task.type == TaskType.delivery:
                    done_worklist.append(task.work_id)
        
        for work_id,work in self.work_dict.items():
            if work_id in done_worklist:
                work.status.type = WorkStatusType.done


    def make_aftertask(self, vty_response: dict):
        vehicle_tasks: list[VehicleTasks] = []

        for vehicle in vty_response['routes']:
            tasks: list[Task] = []
            for step in vehicle['steps']:
                eta = step['arrival']
                duration = step['duration']
                distance = step['distance']
                setup_time = step['setup']
                service_time = step['service']
                location = (step['location'][0], step['location'][1])

                if step['type'] in ['job', 'pickup', 'delivery']:
                    index_type, work_id = self.id_handler.get_id(step['id'])

                    if index_type in ['pickup', 'shipment_pickup']:
                        tasks.append(Task(
                            work_id=work_id,
                            type=TaskType.pickup,
                            eta=eta,
                            duration=duration,
                            distance=distance,
                            setup_time=setup_time,
                            service_time=service_time,
                            assembly_id=None,
                            location=location,
                        ))

                    elif index_type in ['delivery', 'shipment_delivery']:
                        tasks.append(Task(
                            work_id=work_id,
                            type=TaskType.delivery,
                            eta=eta,
                            duration=duration,
                            distance=distance,
                            setup_time=setup_time,
                            service_time=service_time,
                            location=location,
                        ))

            vehicle, vehicle_id = self.id_handler.get_id(vehicle['vehicle'])
            vehicle_tasks.append(VehicleTasks(
                vehicle_id=vehicle_id,
                tasks=tasks,
            ))

        return vehicle_tasks

    def make_beforewave_response(self, vty_responses: dict[str, dict]):
        vehicle_tasks: list[VehicleTasks] = []
        unassigned = []

        for vehicle_id, vehicle in self.vehicle_dict.items():
            tasks: list[Task] = []
            if vehicle_id in vty_responses:
                vty_response = vty_responses[vehicle_id]
                for unassignedtask in vty_response['unassigned']:
                    index_type, work_id = self.id_handler.get_id(unassignedtask['id'])
                    unassigned.append(work_id)

                routes_dict = {v['vehicle']: v for v in vty_response['routes']}

                vehicle_index = self.id_handler.vehicle_index(vehicle_id)
                if vehicle_index in routes_dict:
                    routes = routes_dict[vehicle_index]

                    for step in routes['steps']:
                        eta = step['arrival']
                        duration = step['duration']
                        distance = step['distance']
                        setup_time = step['setup']
                        service_time = step['service']
                        location = (step['location'][0], step['location'][1])

                        if step['type'] in ['job', 'pickup', 'delivery']:
                            index_type, work_id = self.id_handler.get_id(step['id'])
                            if index_type in ['pickup', 'shipment_pickup']:

                                tasks.append(Task(
                                    work_id=work_id,
                                    type=TaskType.pickup,
                                    eta=eta,
                                    duration=duration,
                                    distance=distance,
                                    setup_time=setup_time,
                                    service_time=service_time,
                                    assembly_id=None,
                                    location=location,
                                ))

                            elif index_type in ['delivery', 'shipment_delivery']:
                                tasks.append(Task(
                                    work_id=work_id,
                                    type=TaskType.delivery,
                                    eta=eta,
                                    duration=duration,
                                    distance=distance,
                                    setup_time=setup_time,
                                    service_time=service_time,
                                    assembly_id=None,
                                    location=location,
                                ))
                        elif step['type'] in ['end']:
                            for assembly_id, assembly in self.assembly_dict.items():
                                if assembly.location == location:
                                    tasks.append(Task(
                                        work_id=None,
                                        type=TaskType.arrival,
                                        eta=eta,
                                        setup_time=setup_time,
                                        service_time=service_time,
                                        assembly_id=assembly_id,
                                        location=location,
                                    ))


            vehicle_tasks.append(VehicleTasks(
                vehicle_id=vehicle_id,
                tasks=tasks,
            ))

        return Start_Response(
            vehicle_tasks=vehicle_tasks,
            unassigned=unassigned,
        )

    def make_afterwave_response(self, before_tasks: list[VehicleTasks], after_tasks: list[VehicleTasks]):
        swaps: list[VehicleSwaps] = []
        end_time = []

        for vehicle_id, vehicle in self.vehicle_dict.items():
            shipped_tasks = []
            need_tasks = []

            for vehicle_tasks in before_tasks:
                if vehicle_tasks.vehicle_id == vehicle_id:
                    for task in vehicle_tasks.tasks:
                        if task.work_id is not None: shipped_tasks.append(task.work_id)
                        if task.type == TaskType.arrival: end_time.append(task.eta)

            # wave2 이전에 shipped된 work추가
            for _, work in self.work_dict.items():
                if work.status.type == WorkStatusType.shipped:
                    if work.status.vehicle_id == vehicle_id:
                        shipped_tasks.append(work.id)

            for deliver_tasks in after_tasks:
                if deliver_tasks.vehicle_id == vehicle_id:
                    for task in deliver_tasks.tasks:
                        if task.work_id is not None: need_tasks.append(task.work_id)

            up = list(set(need_tasks) - set(shipped_tasks))
            down = list(set(shipped_tasks) - set(need_tasks))

            swaps.append(VehicleSwaps(vehicle_id=vehicle_id,
                                      assembly_id=next(iter(self.assembly_dict.values())).id,
                                      stopover_time=0,
                                      up=up,
                                      down=down,
                                      ))

        for swap in swaps:
            swap.stopover_time = max(end_time)

        return End_Response(before_tasks=before_tasks, after_tasks=after_tasks, swaps=swaps)

    async def auto_wave2(self):
        vehicle_groups = dict()
        vehicle_works: dict[str, list[Work]] = dict()
        vty_responses = dict()


        for vehicle_id, vehicle in self.vehicle_dict.items():
            vehicle_works[vehicle_id] = []
            for group_id in vehicle.include:
                vehicle_groups[group_id] = vehicle_id

        for _, work in self.work_dict.items():
            # 기사의 재량으로 제외권역 follow up
            if work.exception:
                if work.fix_vehicle_id is None:
                    raise HTTPException(422, "Not found fix_vehicle_id")
                vehicle_works[work.fix_vehicle_id].append(work)
                continue

            # 초기 권역에 포함되지 않은 주문 생략 
            if work.pickup.group_id not in vehicle_groups:
                continue
            handling_vehicle_id = vehicle_groups[work.pickup.group_id]
            vehicle_works[handling_vehicle_id].append(work)

        for _, vehicle in self.vehicle_dict.items():
            vty_jobs = []
            vty_shipments = []
            vty_vehicles = []

            for work in vehicle_works[vehicle.id]:
                # WorkStatus가 현재 pickup한 상태인경우 제외
                if work.status.type == WorkStatusType.waiting:
                    pickup_job = work.pickup.to_job(index=self.id_handler.pickup_index(work.id))
                    vty_jobs.append(pickup_job)

            vehicle_index = self.id_handler.vehicle_index(vehicle.id)

            if vehicle.include[0] in ["A-1","A-2"]:
                vty_vehicle = {
                    'id': vehicle_index,
                    'profile': vehicle.profile.value,
                    'start': vehicle.current_location,
                }
            elif vehicle.include[0] in ["B-0","B-1"]:
                vty_vehicle = {
                    'id': vehicle_index,
                    'profile': vehicle.profile.value,
                    'start': vehicle.current_location,
                    'end': self.assembly_dict["오등동센터"].location
            }
            elif vehicle.include[0] in ["C-0","C-1"]:
                vty_vehicle = {
                    'id': vehicle_index,
                    'profile': vehicle.profile.value,
                    'start': vehicle.current_location,
                    'end': self.assembly_dict["중문동"].location
            }
            elif vehicle.include[0] in ["D-0","D-1"]:
                vty_vehicle = {
                    'id': vehicle_index,
                    'profile': vehicle.profile.value,
                    'start': vehicle.current_location,
                    'end': self.assembly_dict["오등동센터"].location
            }
                
            vty_vehicles.append(vty_vehicle)

            if len(vty_jobs) == 0 and len(vty_shipments) == 0:
                continue

            vroouty_request = {
                'jobs': vty_jobs,
                'shipments': vty_shipments,
                'vehicles': vty_vehicles,
                'distribute_options': {
                    'custom_matrix': {
                        'enabled': True
                    }
                }
            }

            status, vty_response = await vroouty.Post(vroouty_request)
            vty_responses[vehicle.id] = vty_response


        return vty_responses
    
    async def auto_vehicle_A(self, vehicles_tasks, vehicle_eta):
        work_list = []
        vty_jobs =[]
        vty_shipments =[]
        vty_vehicles = []

        for vehicle_tasks in vehicles_tasks.vehicle_tasks:
            if vehicle_tasks.vehicle_id == '기사 A':
                
                for task in vehicle_tasks.tasks:
                    work_list.append(task.work_id)

                for work_id, work in self.work_dict.items():
                    if work_id in work_list:
                        vty_jobs.append(work.pickup.to_job(index=self.id_handler.pickup_index(work_id)))
                
                vty_vehicles.append({
                    'id': self.id_handler.vehicle_index(vehicle_tasks.vehicle_id),
                    'profile': 'car',
                    'start': self.assembly_dict["오등동센터"].location,
                    'end': self.assembly_dict["공항동"].location
                })
                break

        vroouty_request = {
                    'jobs': vty_jobs,
                    'shipments': vty_shipments,
                    'vehicles': vty_vehicles,
                    'distribute_options': {
                        'max_vehicle_work_time': vehicle_eta,
                        'custom_matrix': {
                            'enabled': True
                        }
                    }
                }
        
        status, vty_response = await vroouty.Post(vroouty_request)
        unassigned = vty_response['unassigned']

        return vty_response,unassigned
        
    
    async def auto_vehicle_BD(self, vehicles_tasks, unassigned):
        work_list = []
        unassigned_list =[]
        vty_jobs =[]
        vty_shipments =[]
        vty_vehicles = []

        for vehicle_tasks in vehicles_tasks.vehicle_tasks:
            if vehicle_tasks.vehicle_id in ['기사 B','기사 D']:
                for task in vehicle_tasks.tasks:
                    work_list.append(task.work_id)
    
                vty_vehicles.append({
                    'id': self.id_handler.vehicle_index(vehicle_tasks.vehicle_id),
                    'profile': 'car',
                    'start': self.assembly_dict["오등동센터"].location,
                    'end': self.assembly_dict["공항동"].location
                })

        for work in unassigned:
            unassigned_list.append(work['id'])

        for work_id, work in self.work_dict.items():
            if work_id in work_list:
                vty_jobs.append(work.pickup.to_job(index=self.id_handler.pickup_index(work.id)))
            elif self.id_handler.pickup_index(work_id) in unassigned_list:
                vty_jobs.append(work.pickup.to_job(index=self.id_handler.pickup_index(work.id)))


        vroouty_request = {
                    'jobs': vty_jobs,
                    'shipments': vty_shipments,
                    'vehicles': vty_vehicles,
                    'distribute_options': {
                        'equalize_work_time': {
                        'enabled': True
                        },
                        'custom_matrix': {
                            'enabled': True
                        }
                    }
                }

        status, vty_response = await vroouty.Post(vroouty_request)

        return vty_response

    def auto_before_response(self,task_defualt ,task_a, task_bd):
        vehicle_tasks: list[VehicleTasks] = []

        for vehicle in task_a['routes']:
            tasks: list[Task] = []
            for step in vehicle['steps']:
                eta = step['arrival']
                duration = step['duration']
                distance = step['distance']
                setup_time = step['setup']
                service_time = step['service']
                location = (step['location'][0], step['location'][1])

                if step['type'] in ['job', 'pickup', 'delivery']:
                    index_type, work_id = self.id_handler.get_id(step['id'])

                    if index_type in ['pickup', 'shipment_pickup']:
                        tasks.append(Task(
                            work_id=work_id,
                            type=TaskType.pickup,
                            eta=eta,
                            duration=duration,
                            distance=distance,
                            setup_time=setup_time,
                            service_time=service_time,
                            assembly_id=None,
                            location=location,
                        ))

                    elif index_type in ['delivery', 'shipment_delivery']:
                        tasks.append(Task(
                            work_id=work_id,
                            type=TaskType.delivery,
                            eta=eta,
                            duration=duration,
                            distance=distance,
                            setup_time=setup_time,
                            service_time=service_time,
                            location=location,
                        ))
                elif step['type'] in ['end']:
                    for assembly_id, assembly in self.assembly_dict.items():
                        if assembly.location == location:
                            tasks.append(Task(
                                work_id=None,
                                type=TaskType.arrival,
                                eta=eta,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=assembly_id,
                                location=location,
                            ))


            vehicle, vehicle_id = self.id_handler.get_id(vehicle['vehicle'])
            vehicle_tasks.append(VehicleTasks(
                vehicle_id=vehicle_id,
                tasks=tasks,
            ))
        
        for vehicle in task_bd['routes']:
            tasks: list[Task] = []
            for step in vehicle['steps']:
                eta = step['arrival']
                duration = step['duration']
                distance = step['distance']
                setup_time = step['setup']
                service_time = step['service']
                location = (step['location'][0], step['location'][1])

                if step['type'] in ['job', 'pickup', 'delivery']:
                    index_type, work_id = self.id_handler.get_id(step['id'])

                    if index_type in ['pickup', 'shipment_pickup']:
                        tasks.append(Task(
                            work_id=work_id,
                            type=TaskType.pickup,
                            eta=eta,
                            duration=duration,
                            distance=distance,
                            setup_time=setup_time,
                            service_time=service_time,
                            assembly_id=None,
                            location=location,
                        ))

                    elif index_type in ['delivery', 'shipment_delivery']:
                        tasks.append(Task(
                            work_id=work_id,
                            type=TaskType.delivery,
                            eta=eta,
                            duration=duration,
                            distance=distance,
                            setup_time=setup_time,
                            service_time=service_time,
                            location=location,
                        ))
                elif step['type'] in ['end']:
                    for assembly_id, assembly in self.assembly_dict.items():
                        if assembly.location == location:
                            tasks.append(Task(
                                work_id=None,
                                type=TaskType.arrival,
                                eta=eta,
                                setup_time=setup_time,
                                service_time=service_time,
                                assembly_id=assembly_id,
                                location=location,
                            ))

            vehicle, vehicle_id = self.id_handler.get_id(vehicle['vehicle'])
            vehicle_tasks.append(VehicleTasks(
                vehicle_id=vehicle_id,
                tasks=tasks,
            ))
      
        vehicle_tasks.append(task_defualt.vehicle_tasks[2])

        return vehicle_tasks

    async def auto_vehicle_C_assembly_before_delivery(self,eta):
        vty_jobs =[]
        vty_shipments =[]
        vty_vehicles = []
        done_list = []

        for _, work in self.work_dict.items():
            if work.pickup.group_id in ["C-0","C-1"] and work.delivery.group_id in ["C-0","C-1","CD"]:
                vty_jobs.append(work.delivery.to_job(index=self.id_handler.delivery_index(work.id)))

        vty_vehicles.append({
            'id': self.id_handler.vehicle_index('기사 C'),
            'profile': 'car',
            'start': self.assembly_dict["중문동"].location,
            'end': self.assembly_dict["중문동"].location
        })

        vroouty_request = {
                    'jobs': vty_jobs,
                    'shipments': vty_shipments,
                    'vehicles': vty_vehicles,
                    'distribute_options': {
                        'max_vehicle_work_time': eta,
                        'custom_matrix': {
                            'enabled': True
                        }
                    }
                }
    
        status, vty_response = await vroouty.Post(vroouty_request)

        for step in vty_response['routes'][0]['steps']:
            if step['type'] == 'job':
                done_list.append(self.id_handler.get_id(step['id'])[1])
            
        for work_id,work in self.work_dict.items():
            if work_id in done_list:
                work.status.type = WorkStatusType.done
        
    async def auto_v3_wave3(self):
        vty_jobs =[]
        vty_shipments =[]
        vty_vehicles = []
        
        for _ , work in self.work_dict.items():
            if work.status.type != WorkStatusType.done and work.delivery.group_id in ["C-0","C-1"]:
                vty_jobs.append(work.delivery.to_job(index=self.id_handler.delivery_index(work.id)))
        

        vty_vehicles.append({
            'id': self.id_handler.vehicle_index('기사 C'),
            'profile': 'car',
            'start': self.assembly_dict["중문동"].location
        })

        vroouty_request = {
                    'jobs': vty_jobs,
                    'shipments': vty_shipments,
                    'vehicles': vty_vehicles,
                    'distribute_options': {
                        'custom_matrix': {
                            'enabled': True
                        }
                    }
        }
        
        status, vty_response = await vroouty.Post(vroouty_request)
        return vty_response
    
    async def auto_all_wave3(self,v3_tasks):
        vty_jobs =[]
        vty_shipments =[]
        vty_vehicles = []
        
        for _ , work in self.work_dict.items():
            if work.status.type != WorkStatusType.done and work.delivery.group_id not in ["C-0","C-1"]:
                vty_jobs.append(work.delivery.to_job(index=self.id_handler.delivery_index(work.id)))
        
        for _, vehicle in self.vehicle_dict.items():
            if vehicle.id != '기사 C':
                vty_vehicles.append({
                    'id': self.id_handler.vehicle_index(vehicle.id),
                    'profile': vehicle.profile.value,
                    'start': self.assembly_dict["공항동"].location
                })

        vroouty_request = {
                    'jobs': vty_jobs,
                    'shipments': vty_shipments,
                    'vehicles': vty_vehicles,
                    'distribute_options': {
                        'equalize_work_time': {
                        'enabled': True
                        },
                        'custom_matrix': {
                            'enabled': True
                        }
                    }
                }
        
        status, vty_response = await vroouty.Post(vroouty_request)
        # print(json.dumps(vty_response))
        etas={}
        for vehicle in vty_response['routes']:
            etas[self.id_handler.get_id(vehicle['vehicle'])[1]]=(vehicle['steps'][-1]['arrival'])
        return etas