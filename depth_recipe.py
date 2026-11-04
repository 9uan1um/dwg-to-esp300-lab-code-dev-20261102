"""Offline relative-stage experiment data. This module has NO executor."""
from __future__ import annotations
import hashlib
import json
import math
from copy import deepcopy

SCHEMA = 'offline-depth-recipe-v1'
MODELS = {'x': 'ILS150PP', 'y': 'UTS100PP', 'z': 'GTS150'}

def fingerprint(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()

def default_context():
    return {'origin_revision': 0, 'local_offset': {'x': 0., 'y': 0., 'z': 0.},
            'axis_models_user_reported': dict(MODELS),
            'right_down_controller_signs': {'right': None, 'down': None},
            'mapping_verified': False, 'calibrated': False, 'positive_z': 'deeper, user-reported only'}

def build_recipe(context):
    context = deepcopy(context)
    stamp = fingerprint(context)
    origin=context.get('planning_origin_mm',[0.,0.])
    if len(origin)!=2 or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in origin):raise ValueError('Finite XY planning origin required')
    grid = [(round(c*1.6, 6), round(r*1.6, 6))
            for r in range(7) for c in (range(7) if r % 2 == 0 else range(6,-1,-1))]
    sites = []
    for index, (right, down) in enumerate(grid[1:]):
        right=round(right+origin[0],6);down=round(down+origin[1],6)
        group, within = divmod(index, 24)
        target = round((within // 2)*.3, 6)
        sites.append({'site': index+1, 'grid_order_including_origin': index+2,
                      'group': group+1, 'pair': within//2+1, 'repeat': within%2+1,
                      'logical_right_mm': right, 'logical_down_mm': down,
                      'target_relative_stage_z_mm': target,
                      'ingress': {'from_z_mm': -.5, 'to_z_mm': target,
                                  'requested_speed_mm_s': .4 if group == 0 else .1},
                      'return': {'from_z_mm': target, 'to_z_mm': -.5, 'requested_speed_mm_s': 1.2}})
    return {'schema': SCHEMA, 'executable': False, 'context': context, 'context_fingerprint': stamp,
            'region_mm': [10,10], 'occupied_span_mm': [9.6,9.6], 'pitch_mm': 1.6,
            'origin': ('registered upper-right; logical column/row offsets mapped left/down; first site excluded' if 'substrate_origin_mm' in context else 'upper-left local origin, logical +right/+down; first site excluded'),
            'units': 'mm and mm/s', 'coordinate_meaning': 'relative stage targets, NOT calibrated optical depth or safe limits',
            'beam': 'continuously on; traverse exposure/material effect unverified',
            'xy_traverse_speed_mm_s': None, 'mapping_to_controller': 'unverified; no controller coordinates generated',
            'velocity_note': 'Requested values do not ensure constant actual velocity during acceleration, corners or stops',
            'completion': {'normal_only': True, 'dwell_seconds': 3.0, 'hold_z_mm': context.get('substrate_origin_mm',[0,0,0])[2]-.5, 'xy_target_mm': context.get('substrate_origin_mm',[0.,0.,0.])[:2], 'xy_speed_mm_s': context.get('mock_xy_speed_mm_s'), 'final_z_mm': context.get('substrate_origin_mm',[0,0,0])[2], 'z_speed_mm_s': 1.2, 'on_cancel_or_error': 'stop; no automatic return'},
            'sites': sites}

def validate_recipe(recipe, context):
    if recipe.get('schema') != SCHEMA or recipe.get('executable') is not False:
        return {'valid': False, 'executable': False, 'reason': 'Not an offline recipe'}
    if recipe.get('context_fingerprint') != fingerprint(context):
        return {'valid': False, 'executable': False, 'reason': 'Origin, axis, session or configuration changed; regenerate'}
    if recipe != build_recipe(context):
        return {'valid': False, 'executable': False, 'reason': 'Recipe data changed; regenerate'}
    return {'valid': True, 'executable': False, 'reason': 'Current offline data only; hardware execution is unavailable'}

def reject_execution(*args, **kwargs):
    raise RuntimeError('Depth recipes are offline-only. No hardware executor exists.')

if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Create offline depth data only; no device imports')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    # Exclusive create: never silently overwrite a previous experiment.
    with Path(args.output).open('x', encoding='utf-8') as stream:
        json.dump(build_recipe(default_context()), stream, ensure_ascii=False, indent=2)
