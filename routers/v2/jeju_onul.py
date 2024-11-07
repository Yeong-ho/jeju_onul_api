from fastapi import APIRouter

import json
import asyncio
from models.v2.jeju_onul.internal import OptimizationHandler
from models.v2.jeju_onul.transaction import *

from datetime import datetime, timedelta

def add_seconds_to_time(start_time: str, seconds: int) -> str:
    # 주어진 문자열 형식의 시작 시간을 datetime 객체로 변환
    start_datetime = datetime.strptime(start_time, '%H:%M')
    
    # 초를 timedelta 객체로 변환하여 시작 시간에 더하기
    new_datetime = start_datetime + timedelta(seconds=seconds)
    
    # 새로운 시간을 문자열로 변환하여 반환
    new_time = new_datetime.strftime('%H:%M')
    
    return new_time


router = APIRouter(
    prefix='',
    tags=['apis'],
    dependencies=[],
    responses={},
)

#메인권역 중심 / cut off 이전
@router.post('/jeju_onul_before',
    response_model=Start_Response,
    response_model_exclude_none=True,
)
async def jeju_onul_beforewave(request: Request):
    opt = OptimizationHandler(request)

    vroouty_responses = await opt.process_opt_wave1()
    return opt.make_beforewave_response(vroouty_responses)

#cut off 이후부터 집결이후
@router.post('/jeju_onul_after',
    response_model=End_Response,
    response_model_exclude_none=True,
)
async def jeju_onul_afterwave(request: Request):
    
    opt = OptimizationHandler(request)
    before_tasks = await opt.make_beforetask(await opt.process_opt_wave2())   
    after_tasks = opt.make_aftertask(await opt.process_opt_wave3())

    return opt.make_afterwave_response(before_tasks,after_tasks)

#auto_pilot_assembly before
@router.post('/auto_pilot',response_model_exclude=True)
async def auto_pilot_wave2(request: Request):
    vehicles_etas = []
    opt = OptimizationHandler(request)
    
    first_tasks = opt.make_beforewave_response(await opt.auto_wave2())

    for vehicle_tasks in first_tasks.vehicle_tasks:
        vehicles_etas.append(vehicle_tasks.tasks[-1].eta)

    vehicle_A_tasks, unassigned = await opt.auto_vehicle_A(first_tasks,vehicles_etas[2]+4200) #C집결 후 상차 + 공항동까지 소요시간
    vehicle_B_D_tasks = await opt.auto_vehicle_BD(first_tasks,unassigned)

    assembly_1 = add_seconds_to_time('09:00',vehicles_etas[2])
    assembly_2 = add_seconds_to_time(assembly_1,4200)
    assembly_3 = add_seconds_to_time(assembly_2,4200)
    
    print(f"C 중문동 집결 : {assembly_1}")
    print(f"A 공항동 집결 : {assembly_2}")
    print(f"C 중문동 재집결 : {assembly_3}")


    auto_pilot_before_tasks = opt.auto_before_response(first_tasks,vehicle_A_tasks,vehicle_B_D_tasks)

    await opt.auto_vehicle_C_assembly_before_delivery(3000+4200)

    v3_tasks = await opt.auto_v3_wave3()

    print(f"C 기사 마감 :{add_seconds_to_time(assembly_3, v3_tasks['routes'][0]['steps'][-1]['arrival']+1800)}")
    print(f"기사 C : {v3_tasks['routes'][0]['steps'][-1]['arrival']}")
    all_tasks = await opt.auto_all_wave3(v3_tasks)
    print(f"중문동 집결 후 출발 시간 : {add_seconds_to_time(assembly_3,1800)}" )
    print(all_tasks)
    for vehicle_id ,eta in all_tasks.items():
        print(f"{vehicle_id} : {add_seconds_to_time(assembly_2,eta+1800)}") # A집결에 상하차(1800sec) 후 바로 배송 시간

    return first_tasks