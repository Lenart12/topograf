from enum import Enum
from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, field_validator, model_validator
import json
from pathlib import Path
import argparse
import sys


class RasterType(str, Enum):
    DTK50 = "dtk50"
    DTK25 = "dtk25"
    OSM = "osm"
    OTM = "otm"
    EMPTY = ""


class ControlPointKind(str, Enum):
    CIRCLE = "circle"
    TRIANGLE = "triangle"
    DOT = "dot"
    SKIP = "skip"
    POINT = "point"


class ControlPointOptions(BaseModel):
    n: float  # northing in meters (D96/TM)
    e: float  # easting in meters (D96/TM)
    name: Optional[str] = None  # name of the control point
    kind: ControlPointKind
    color: str
    color_line: str
    connect_next: bool
    x: Optional[float] = None  # x position on the map (while drawing)
    y: Optional[float] = None  # y position on the map (while drawing)


class ControlPointsConfig(BaseModel):
    cp_size: float  # size of the control point in meters
    cp_name_shadow: bool  # show name shadow
    cp_line_start_offset: float # offset for the start of the line in meters
    cps: List[ControlPointOptions]
    bounds: Optional[Tuple[float, float, float, float]] = None


class RequestType(str, Enum):
    MAP_PREVIEW = "map_preview"
    CREATE_MAP = "create_map"


class MapBaseRequest(BaseModel):
    id: str = ""
    request_type: RequestType
    map_w: float
    map_s: float
    map_e: float
    map_n: float
    epsg: str
    raster_type: RasterType
    raster_source: str = ""
    map_size_w_m: float
    map_size_h_m: float
    output_folder: str = ""

    @model_validator(mode='after')
    def validate_map_bounds(self) -> 'MapBaseRequest':
        if self.map_w >= self.map_e:
            raise ValueError('map_w >= map_e')
        if self.map_s >= self.map_n:
            raise ValueError('map_s >= map_n')
        return self

    @field_validator("epsg")
    @classmethod
    def validate_epsg(cls, v: str) -> str:
        import re
        if not re.match(r'^EPSG:\d+$|^Brez$', v):
            raise ValueError('Koordinatni sistem je napačen (EPSG:xxxx ali Brez)')
        return v

    @field_validator('map_size_w_m')
    @classmethod
    def validate_map_size_w(cls, v: float) -> float:
        if v > 1:
            raise ValueError('Velikost karte je prevelika (širina) (max 1m)')
        return v

    @field_validator('map_size_h_m')
    @classmethod
    def validate_map_size_h(cls, v: float) -> float:
        if v > 1:
            raise ValueError('Velikost karte je prevelika (višina) (max 1m)')
        return v

    @classmethod
    def from_args(cls, args: Dict[str, Any]):
        """Create instance from command line arguments dictionary"""

        raster_type = args["raster_type"]
        epsg = args["epsg"]
        if raster_type == RasterType.DTK25:
            epsg = "EPSG:3912"

        return cls(
            id=args.get("id", ""),
            request_type=args["request_type"],
            map_w=float(args["map_w"]),
            map_s=float(args["map_s"]),
            map_e=float(args["map_e"]),
            map_n=float(args["map_n"]),
            epsg=epsg,
            raster_type=raster_type,
            raster_source=args.get("raster_source", ""),
            map_size_w_m=float(args["map_size_w_m"]),
            map_size_h_m=float(args["map_size_h_m"]),
            output_folder=args.get("output_folder", "")
        )


class MapPreviewRequest(MapBaseRequest):    
    @classmethod
    def from_args(cls, args: Dict[str, Any]):
        """Create instance from command line arguments dictionary"""
        base = MapBaseRequest.from_args(args)
        return cls(
            id=base.id,
            request_type=base.request_type,
            map_w=base.map_w,
            map_s=base.map_s,
            map_e=base.map_e,
            map_n=base.map_n,
            epsg=base.epsg,
            raster_type=base.raster_type,
            raster_source=base.raster_source,
            map_size_w_m=base.map_size_w_m,
            map_size_h_m=base.map_size_h_m,
            output_folder=base.output_folder
        )


class MapCreateRequest(MapBaseRequest):
    target_scale: int
    edge_wgs84: bool
    naslov1: str
    naslov2: str
    dodatno: str
    slikal: str = ""
    slikad: str = ""
    control_points: ControlPointsConfig

    @field_validator('target_scale')
    @classmethod
    def validate_target_scale(cls, v: int) -> int:
        if v < 1000:
            raise ValueError('Merilo je napačno ali preveliko (max 1:1000)')
        if v > 100000:
            raise ValueError('Merilo je napačno ali preveliko (max 1:100000)')
        return v

    @field_validator('naslov1')
    @classmethod
    def validate_naslov1(cls, v: str) -> str:
        if len(v) > 30:
            raise ValueError('Naslov (1) je predolg (max 30 znakov)')
        return v

    @field_validator('naslov2')
    @classmethod
    def validate_naslov2(cls, v: str) -> str:
        if len(v) > 30:
            raise ValueError('Naslov (2) je predolg (max 30 znakov)')
        return v

    @field_validator('dodatno')
    @classmethod
    def validate_dodatno(cls, v: str) -> str:
        if len(v) > 70:
            raise ValueError('Dodatna vrstica je predolgo (max 70 znakov)')
        return v
    
    @classmethod
    def from_args(cls, args: Dict[str, Any]):
        """Create instance from command line arguments dictionary"""
        base = MapBaseRequest.from_args(args)
        
        # Parse control_points JSON string into ControlPointsConfig
        control_points_data = json.loads(args["control_points"])
        control_points_config = ControlPointsConfig(**control_points_data)
        
        return cls(
            id=base.id,
            request_type=base.request_type,
            map_w=base.map_w,
            map_s=base.map_s,
            map_e=base.map_e,
            map_n=base.map_n,
            epsg=base.epsg,
            raster_type=base.raster_type,
            raster_source=base.raster_source,
            map_size_w_m=base.map_size_w_m,
            map_size_h_m=base.map_size_h_m,
            target_scale=int(args["target_scale"]),
            edge_wgs84=args["edge_wgs84"].lower() == "true",
            naslov1=args["naslov1"],
            naslov2=args["naslov2"],
            dodatno=args["dodatno"],
            slikal=args.get("slikal", ""),
            slikad=args.get("slikad", ""),
            control_points=control_points_config,
            output_folder=base.output_folder
        )


def parse_command_line_args(args=None):
    """
    Parse command line arguments for map requests.
    """
    parser = argparse.ArgumentParser(description="Process map creation or preview requests")
    
    # Required arguments
    parser.add_argument("--id", type=str, help="Request ID", default="", required=True)
    parser.add_argument("--request_type", type=str, choices=["map_preview", "create_map"], 
                        help="Type of request (map_preview or create_map)", required=True)
    parser.add_argument("--map_w", type=float, help="West bound", required=True)
    parser.add_argument("--map_s", type=float, help="South bound", required=True)
    parser.add_argument("--map_e", type=float, help="East bound", required=True)
    parser.add_argument("--map_n", type=float, help="North bound", required=True)
    parser.add_argument("--epsg", type=str, help="EPSG code", required=True)
    parser.add_argument("--raster_type", type=str, help="Raster type", required=True)
    parser.add_argument("--raster_source", type=str, help="Raster source path", default="", required=True)
    parser.add_argument("--map_size_w_m", type=float, help="Map width in meters", required=True)
    parser.add_argument("--map_size_h_m", type=float, help="Map height in meters", required=True)
    parser.add_argument("--output_folder", type=str, help="Output folder path",required=True)
    
    # Create map specific arguments
    parser.add_argument("--target_scale", type=int, help="Target scale")
    parser.add_argument("--edge_wgs84", type=str, help="Include WGS84 edge markings")
    parser.add_argument("--naslov1", type=str, help="Primary title")
    parser.add_argument("--naslov2", type=str, help="Secondary title")
    parser.add_argument("--dodatno", type=str, help="Additional information")
    parser.add_argument("--slikal", type=str, help="Left image path", default="")
    parser.add_argument("--slikad", type=str, help="Right image path", default="")
    parser.add_argument("--control_points", type=str, help="Control points as JSON string")

    # Utility arguments
    parser.add_argument("--emit-progress", action="store_true", help="Emit progress events", default=False)
    
    if args is None:
        args = sys.argv[1:]
        
    parsed_args = parser.parse_args(args)
    return vars(parsed_args)


def create_request_from_args(args_dict):
    """
    Create appropriate request object based on request type.
    """
    request_type = args_dict.get("request_type")
    
    if request_type == "map_preview":
        return MapPreviewRequest.from_args(args_dict)
    elif request_type == "create_map":
        return MapCreateRequest.from_args(args_dict)
    else:
        raise ValueError(f"Unknown request type: {request_type}")
