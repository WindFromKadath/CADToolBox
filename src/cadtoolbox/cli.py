"""Catalog and geometry commands. Geometry modules load only when requested."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .catalog import CatalogError, get_item, load_collection, validate_project
from .contracts import Axis, ContractError, ShapeExpectation, ShapeKind, Unit


def _print(data):
    print(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))


def _output_inside(root: Path, path: Path) -> Path:
    target = (root/path).resolve() if not path.is_absolute() else path.resolve()
    if not target.is_relative_to(root.resolve()):
        raise ContractError('output must be inside CADToolbox project root')
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='CADToolbox 工具、方法与几何检查')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest='command',required=True)
    for command in ['list-tools','list-methods']:
        sub.add_parser(command).add_argument('--json',action='store_true')
    for command in ['show-tool','show-method']:
        sub.add_parser(command).add_argument('id')
    sub.add_parser('check').add_argument('--sources',action='store_true')
    for name in ['inspect-step','roundtrip-step']:
        p = sub.add_parser(name)
        p.add_argument('input',type=Path)
        p.add_argument('--kind',choices=[k.value for k in ShapeKind])
        p.add_argument('--solids',type=int)
        if name == 'inspect-step':
            p.add_argument('--axis',nargs=6,type=float,metavar=('X','Y','Z','DX','DY','DZ'))
        else:
            p.add_argument('output',type=Path)
            p.add_argument('--overwrite',action='store_true')
    p = sub.add_parser('inspect-dxf')
    p.add_argument('input',type=Path)
    p.add_argument('--unit',choices=[u.value for u in Unit])
    p.add_argument('--layers',nargs='+')
    sub.add_parser('demo-io').add_argument('--output',type=Path,required=True)
    for command in ['build-rotor','build-surface-blade','build-solved-profile','build-raster-profile','extract-image-candidates']:
        p=sub.add_parser(command)
        p.add_argument('config',type=Path)
        p.add_argument('--output',type=Path,required=True)
    sub.add_parser('solve-sketch').add_argument('config',type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command in {'list-tools','list-methods'}:
            kind = 'tool' if args.command == 'list-tools' else 'method'
            items = load_collection(args.root,kind)
            if args.json:
                _print(items)
            else:
                for item in items:
                    status = item.get('implementation_status',item.get('validation_status'))
                    print(f"{item['id']}\t{status}\t{item['name']}")
            return 0
        if args.command in {'show-tool','show-method'}:
            _print(get_item(args.root,'tool' if args.command == 'show-tool' else 'method',args.id))
            return 0
        if args.command == 'check':
            result = validate_project(args.root,check_sources=args.sources)
            _print(result)
            return 0 if result['success'] else 1
        if args.command == 'solve-sketch':
            from .solver.sketch import solve_sketch
            config=json.loads(args.config.read_text(encoding='utf-8-sig'))
            result=solve_sketch(config['sketch'],**config.get('solver_options',{}))
            _print(result)
            return 0 if result['success'] else 2
        if args.command in {'build-raster-profile','extract-image-candidates'}:
            from .workflows.raster import run_raster
            _print(run_raster(args.config,_output_inside(args.root,args.output),candidates=args.command=='extract-image-candidates',progress=lambda name:print('completed '+name,file=sys.stderr)))
            return 0
        from .geometry.io import export_step, load_dxf, load_step
        from .geometry.measure import measure
        if args.command == 'inspect-dxf':
            _print(load_dxf(args.input,input_unit=Unit(args.unit) if args.unit else None,include_layers=args.layers).report)
        elif args.command == 'build-solved-profile':
            from .workflows.solved_profile import run_solved_profile
            _print(run_solved_profile(args.config,_output_inside(args.root,args.output),progress=lambda name:print('completed '+name,file=sys.stderr)))
        elif args.command == 'build-surface-blade':
            from .workflows.surfaces import run_surface_blade
            _print(run_surface_blade(args.config,_output_inside(args.root,args.output),progress=lambda name:print('completed '+name,file=sys.stderr)))
        elif args.command == 'build-rotor':
            from .workflows.rotor import run_rotor
            _print(run_rotor(args.config,_output_inside(args.root,args.output),progress=lambda name:print('completed '+name,file=sys.stderr)))
        elif args.command == 'demo-io':
            from .workflows.io_demo import run_io_demo
            _print(run_io_demo(_output_inside(args.root,args.output)))
        else:
            expected = None
            if args.kind:
                count = args.solids if args.solids is not None else (1 if args.kind=='Solid' else 0)
                expected = ShapeExpectation(ShapeKind(args.kind),count)
            elif args.solids is not None:
                raise ContractError('--solids requires --kind')
            loaded = load_step(args.input,expected)
            if args.command == 'inspect-step':
                axis = Axis(tuple(args.axis[:3]),tuple(args.axis[3:])) if args.axis else None
                _print({'success':True,'import':loaded.report,'measurement':measure(loaded.shape,axis)})
            else:
                if expected is None:
                    raise ContractError('roundtrip-step requires explicit --kind and solid count when Compound')
                _print(export_step(loaded.shape,_output_inside(args.root,args.output),expected,overwrite=args.overwrite))
        return 0
    except (CatalogError,ContractError) as exc:
        print(str(exc),file=sys.stderr)
        return 2
    except Exception as exc:
        from .geometry.quality import GeometryError
        if isinstance(exc,GeometryError):
            _print(exc.as_dict())
            return 2
        raise  # Unexpected programming errors must retain their traceback.


if __name__=='__main__':
    raise SystemExit(main())
