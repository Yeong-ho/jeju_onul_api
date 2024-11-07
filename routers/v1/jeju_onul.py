from fastapi import APIRouter

from models.v1.jeju_onul.algorithm import *
from models.v1.jeju_onul.internal import *
from models.v1.jeju_onul.transaction import *

router = APIRouter(
    prefix='',
    tags=['apis'],
    dependencies=[],
    responses={},
)

@router.post('/jeju_onul',
    response_model=Response,
    response_model_exclude_none=True,
)
async def jeju_onul(request: Request):

    opt = OptimizationHandler(request)

    await opt.first_optimization(request)

    best_response, best_stopover_time, best_cost = None, None, 10e20

    if request.algorithm.second_assembly.type == SecondAssemblyAlgorithmType.handle_pickup:

        stopover_time = opt.wave_2_stopover_times

        so_response = await opt.second_optimization(request, stopover_time)

        cost = cost_function(opt, so_response)

        best_response, best_stopover_time, best_cost = so_response, stopover_time, cost
    
    elif request.algorithm.second_assembly.type == SecondAssemblyAlgorithmType.select_best:

        for assembly_time in request.algorithm.second_assembly.assembly_time_candidates:

            start = opt.waves.w2.start_time
            
            stopover_time = { k: start + assembly_time for k, _ in opt.assembly_dict.items() }
            print('stopover_time:', stopover_time)

            try:
                so_response = await opt.second_optimization(request, stopover_time)

                cost = cost_function(opt, so_response)
                print('assembly_time:', assembly_time, 'cost:', cost)

                if best_cost > cost:
                    best_response, best_stopover_time, best_cost = so_response, stopover_time, cost
            
            except Exception as e:
                print('assembly_time:', assembly_time, 'calculation error:', e)

    print('best:', best_stopover_time, best_cost)

    resp = await opt.make_response(request, best_response, best_stopover_time)

    return resp

def cost_function(opt: OptimizationHandler, resp) -> int:
    vehicle_count = len(resp['routes'])

    routes_dict = { v['vehicle']: v for v in resp['routes'] }

    distances = []

    for vs in opt.waves.w3.vehicles:
        vehicle_index = opt.waves.w3.vehicle_id_to_index(vs.id)

        if vehicle_index in routes_dict:

            route = routes_dict[vehicle_index]
            distances.append(route['steps'][-1]['distance'])

    print('vc:', vehicle_count, 'distances:', distances)

    return int(sum(distances))
