import datetime
import traceback
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import sys
import math
import json
import pyproj
import json
import pyproj.transformer
import rasterio
import rasterio.merge
import rasterio.plot
import rasterio.transform
import rasterio.enums
import shapely
import json
import os
import tempfile
import hashlib
import numpy as np
import logging
import contextily
import xyzservices
import dto
import img2pdf
import requests
from progress import ProgressTracker, NoProgress, ProgressError
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import io
from matplotlib.ticker import MaxNLocator

### STATIC CONFIGURATION ###

# General settings
INPUT_CONTEXT = None # Set path to error json file to reproduce the error
USE_CACHE = True
TARGET_DPI = 318
PDF_AUTHOR = 'Topograf - topograf.scuke.si'

# Map settings
GRID_MARGIN_M = [0.011, 0.0141, 0.0195, 0.0143] # Margin around the A4 paper in meters [top, right, bottom, left]

# Control point reporting settings
CP_REPORT_PAGE_SIZE_M = (0.21, 0.297) # A4
CP_REPORT_PAGE_MARGIN_M = (0.012, 0.017, 0.012, 0.017) # Margin around the A4 paper in meters [top, right, bottom, left]
CP_REPORT_GRID_SIZE = (2, 6) # 2x6 grid
CP_REPORT_PREVIEW_SIZE_RADIUS_M = 300 # Radius of the preview image in meters

### /STATIC CONFIGURATION ###

# Setup logging
logger = logging.getLogger('create_map')
logger.setLevel(logging.DEBUG)

OUTPUT_DIR = os.path.join(tempfile.gettempdir(), '.create_map_cache')

def get_cache_dir(folder: str = ''):
    cache_dir = OUTPUT_DIR
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    if folder:
        cache_dir = os.path.join(cache_dir, folder)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

    return cache_dir

def get_cache_index(o: dict):
    return hashlib.md5(json.dumps(o, sort_keys=True).encode('utf-8')).hexdigest()

def get_raster_map_bounds(raster_folder: str, pt: ProgressTracker = NoProgress):
    """
    Returns the bounds of the rasters inside the folder as a dictionary with the filename as the key.

    Parameters
    ----------
    raster_folder : str
        The folder containing the raster files.
    """
    pt.step(0)
    folder_hash = get_cache_index({'raster_folder': os.path.abspath(raster_folder)})
    bounds_cache_fn = os.path.join(get_cache_dir('tile_bounds'), f'{folder_hash}-bounds-cache.json')

    if os.path.exists(bounds_cache_fn) and USE_CACHE:
        with open(bounds_cache_fn, 'r') as f:
            pt.step(0.9)
            bounds = json.load(f)
            pt.step(1)
            logger.info(f'Using cached raster bounds. - ({folder_hash})')
            return bounds

    raster_files = [f for f in os.listdir(raster_folder) if f.endswith(".tif")]
    bounds = {}
    for filename in pt.over_range(0.1, 0.9, raster_files):
        fp = os.path.join(raster_folder, filename)
        with rasterio.open(fp) as src:
            bounds[filename] = [*src.bounds]

    with open(bounds_cache_fn, 'w') as f:
        json.dump(bounds, f)

    pt.step(1)
    logger.info(f'Discovered raster bounds. - ({folder_hash})')
    return bounds

def get_raster_map_tiles(tiles_url: str, zoom_adjust: int, max_zoom: int, bounds: tuple[float], pt: ProgressTracker = NoProgress):
    """
    Gets the raster map from a tile server.
    
    Parameters
    ----------
    tiles_url : str
        The URL of the tile server.
    bounds : tuple (west, south, east, north)
        The bounds of the area to be merged. EPSG:3794
    """
    pt.step(0)

    crs_from = pyproj.CRS.from_epsg(3794)
    crs_to = pyproj.CRS.from_epsg(3857)
    transformer = pyproj.Transformer.from_crs(crs_from, crs_to)

    # Convert bounds to EPSG:3857
    corners = [
        transformer.transform(bounds[0], bounds[1]), # SW
        transformer.transform(bounds[2], bounds[1]), # SE
        transformer.transform(bounds[2], bounds[3]), # NE
        transformer.transform(bounds[0], bounds[3])  # NW
    ]
    bounds_3857 = [
        min(c[0] for c in corners),
        min(c[1] for c in corners),
        max(c[0] for c in corners),
        max(c[1] for c in corners)
    ]

    # Get the tiles
    logger.info(f'Getting raster map tiles. - ({bounds_3857})')
    try:
        # Download the tiles
        pt.step(0.1)
        source = xyzservices.TileProvider(url=tiles_url, attribution="", name="url", max_zoom=max_zoom)
        contextily.set_cache_dir(get_cache_dir('tiles'))
        logger.info(f'Using zoom adjustment of {zoom_adjust}')
        mosaic_web, extent_web = contextily.bounds2img(*bounds_3857, source=source, zoom_adjust=zoom_adjust)
        # Warp the tiles to EPSG:3794
        pt.step(0.6)
        mosaic_d96, extent_d96 = contextily.warp_tiles(mosaic_web, extent_web, 'EPSG:3794', rasterio.enums.Resampling.lanczos)
        pt.step(0.7)

        # Crop the tiles to the bounds
        bands = mosaic_d96.shape[2]
        # Remove the alpha channel if it exists
        if bands == 4:
            mosaic_d96 = mosaic_d96[:,:,:3]
            bands = 3

        transform = rasterio.transform.from_bounds(
            extent_d96[0], extent_d96[2],
            extent_d96[1], extent_d96[3],
            mosaic_d96.shape[1], mosaic_d96.shape[0]
        )
        with rasterio.io.MemoryFile() as memfile:
            with memfile.open(
                driver='GTiff',
                width=mosaic_d96.shape[1],
                height=mosaic_d96.shape[0],
                count=bands,
                dtype=mosaic_d96.dtype,
                crs='EPSG:3794',
                transform=transform
            ) as dst:
                pt.step(0.8)
                dst.write(rasterio.plot.reshape_as_raster(mosaic_d96))
            with memfile.open() as src:
                pt.step(0.9)
                mosaic = rasterio.merge.merge([src], bounds)[0]
                pt.step(1)
                return mosaic
    except requests.HTTPError as e:
        if '404' in str(e):
            raise ProgressError(f'Rasterski strežnik ne more pokriti željenega območja') from e
        
        raise ProgressError(f'Napaka pri pridobivanju podatkov iz strežnika: {e}') from e
    except Exception as e:
        raise ProgressError(f'Napaka pri pridobivanju podatkov iz strežnika') from e

def get_raster_map(raster_type: dto.RasterType, raster_folder: str, zoom_adjust: int, bounds: tuple[float], pt: ProgressTracker = NoProgress):
    """
    Merges all the raster files in the folder that intersect with the given bounds.

    Parameters
    ----------
    raster_folder : str
        The folder containing the raster files.
    bounds : tuple (west, south, east, north)
        The bounds of the area to be merged. EPSG:3794
    """

    pt.step(0)
    bounds_hash = get_cache_index({'raster_folder': os.path.abspath(raster_folder), 'bounds': bounds, 'zoom_adjust': zoom_adjust})
    raster_cache_fn = os.path.join(get_cache_dir('raster'), f'{bounds_hash}.npy')

    if os.path.exists(raster_cache_fn) and USE_CACHE:
        pt.step(0.9)
        mosaic = np.load(raster_cache_fn)
        logger.info(f'Using cached raster mosaic. - ({bounds_hash} - {mosaic.shape})')
        pt.step(1)
        return mosaic

    if raster_folder.startswith('https://'):
        max_zoom = {
            'osm': 19,
            'otm': 15,
        }.get(raster_type, 19)

        mosaic = get_raster_map_tiles(raster_folder, zoom_adjust, max_zoom, bounds, pt.sub(0.1, 0.9))
        np.save(raster_cache_fn, mosaic)
        pt.step(1)
        logger.info(f'Created raster mosaic. - ({bounds_hash} - {mosaic.shape})')
        return mosaic
    
    pt.step(0)
    crs_from = pyproj.CRS.from_epsg(3794)

    if raster_type == dto.RasterType.DTK25 or \
       raster_type == dto.RasterType.DTK10 or \
       raster_type == dto.RasterType.DTK5:
        crs_to = pyproj.CRS.from_epsg(3912)
        max_files = 6
    elif raster_type == dto.RasterType.DTK50:
        crs_to = pyproj.CRS.from_epsg(3794)
        max_files = 4
    else:
        raise ProgressError('Neveljaven tip osnove za karto')
    
    transformer = pyproj.Transformer.from_crs(crs_from, crs_to)
    west, south = transformer.transform(bounds[0], bounds[1])
    east, north = transformer.transform(bounds[2], bounds[3])
    bounds = (west, south, east, north)

    raster_bounds = get_raster_map_bounds(raster_folder, pt.sub(0.01, 0.1))
    selected_files = []
    bbox = shapely.geometry.box(*bounds)
    for filename, file_bounds in raster_bounds.items():
        file_bbox = shapely.geometry.box(*file_bounds)
        if bbox.intersects(file_bbox):
            selected_files.append(os.path.join(raster_folder, filename))

    if len(selected_files) == 0:
        raise ProgressError('Izbrano območje ne vsebuje nobenih podatkov za ta rasterski sloj')
    
    if len(selected_files) > max_files:
        raise ProgressError('Izbrano območje je preveliko')

    src_files_to_mosaic = []
    for fp in pt.over_range(0.2, 0.8, selected_files):
        src = rasterio.open(fp)
        src_files_to_mosaic.append(src)
    
    mosaic, _ = rasterio.merge.merge(src_files_to_mosaic, bounds=bounds, nodata=255)
    pt.step(0.9)
    np.save(raster_cache_fn, mosaic)
    pt.step(1)

    logger.info(f'Created raster mosaic. - ({bounds_hash} - {mosaic.shape})')
    return mosaic

# Convert decimal degrees to DD°MM'SS" format
def deg_to_deg_min_sec(deg, precision=0):
    d = int(deg)
    m = int((deg - d) * 60)
    if precision > 0:
        s = (deg - d - m / 60) * 3600
        s = round(s, precision)
    else:
      s = int((deg - d - m / 60) * 3600)
    return f'{d}°{m:02}\'{s:02}"'

def get_grid_and_map(map_size_m: tuple[float], map_bounds: tuple[float], raster_type: dto.RasterType, raster_folder: str, zoom_adjust: int, pt: ProgressTracker = NoProgress):
    """
    Returns the map image, the grid image, and the transformers for converting between the map and the world.

    Parameters
    ----------
    map_size_m : tuple (width, height)
        The size of the map in meters.
    map_bounds : tuple (west, south, east, north)
        The bounds of the map in EPSG:3794.
    raster_folder : str
        The folder containing the raster files.
    """
    pt.step(0)
    # Convert from meters to pixels
    target_pxpm = TARGET_DPI / 0.0254
    real_to_map_tr = rasterio.transform.AffineTransformer(
        rasterio.transform.from_bounds(
            0, map_size_m[1],
            map_size_m[0], 0,
            int(map_size_m[0] * target_pxpm),
            int(map_size_m[1] * target_pxpm))
            )

    # Calculate the size of the map in pixels and create a blank image
    map_size_px = [p + 1 for p in real_to_map_tr.rowcol(*map_size_m)[::-1]]
    map_img = Image.new('RGB', map_size_px, 0xFFFFFF)

    # Calculate the size of the grid in pixels
    grid_margin_px = [int(m * target_pxpm) for m in GRID_MARGIN_M]
    grid_size_px = [map_size_px[0] - grid_margin_px[1] - grid_margin_px[3], map_size_px[1] - grid_margin_px[0] - grid_margin_px[2]]

    # Get the raster map
    if raster_folder != '':
        grid_raster = get_raster_map(raster_type, raster_folder, zoom_adjust, map_bounds, pt.sub(0.1, 0.8))
        grid_img = Image.fromarray(rasterio.plot.reshape_as_image(grid_raster), 'RGB').resize(grid_size_px, resample=Image.Resampling.LANCZOS)
        pt.step(0.9)
    else:
        logger.info('Skipping raster map.')
        grid_img = Image.new('RGB', grid_size_px, 0xFFFFFF)
        pt.step(0.9)

    # Create a transformer for converting between the grid and the world
    grid_to_world_tr = rasterio.transform.AffineTransformer(rasterio.transform.from_bounds(*map_bounds, *grid_img.size))

    # Create a transformer for converting between the map and the world
    map_sw = grid_to_world_tr.xy(grid_size_px[1] + grid_margin_px[2], -grid_margin_px[3])
    map_ne = grid_to_world_tr.xy(-grid_margin_px[0], grid_size_px[0] + grid_margin_px[1])
    map_to_world_tr = rasterio.transform.AffineTransformer(rasterio.transform.from_bounds(*map_sw, *map_ne, *map_img.size))

    # Add a helper function that swaps returned columns and rows
    def add_colrow_to_transformer(tr):
        tr.colrow = lambda x, y: tr.rowcol(x, y)[::-1]
        return tr
    
    map_to_grid_offset = map_to_world_tr.rowcol(*grid_to_world_tr.xy(0,0))[::-1]
    def map_to_grid(x, y):
        return (x - map_to_grid_offset[0], y - map_to_grid_offset[1])
    
    logger.info(f'Created map and grid images. ({map_size_px} - {map_bounds})')
    
    pt.step(1)
    return map_img, grid_img, add_colrow_to_transformer(map_to_world_tr), add_colrow_to_transformer(grid_to_world_tr), add_colrow_to_transformer(real_to_map_tr), map_to_grid


def draw_grid(map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, raster_type, epsg, edge_wgs84, map_to_grid, skip_grid_lines, pt: ProgressTracker = NoProgress):
    map_draw = ImageDraw.Draw(map_img)
    pt.step(0)
    # Draw grid on the map
    logger.info('Drawing grid.')
    map_img.paste(grid_img, real_to_map_tr.colrow(GRID_MARGIN_M[3], GRID_MARGIN_M[0]))
    pt.step(0.3)

    # Draw grid border
    logger.info('Drawing grid border.')
    border0 = map_to_world_tr.colrow(*grid_to_world_tr.xy(-1, -1))
    grid_border = (border0[0], border0[1], border0[0] + grid_img.size[0] + 1, border0[1] + grid_img.size[1] + 1)
    map_draw.rectangle(grid_border, outline='black', width=2)
    pt.step(0.4)

    grid_font = ImageFont.truetype('timesi.ttf', 48)
    border_bottom_px = 0

    # Draw coordinate system
    if epsg != 'Brez':
        cs_from = pyproj.CRS.from_epsg(3794)
        cs_to = pyproj.CRS.from_epsg(int(epsg.split(':')[1]))
        cs_from_to_tr = pyproj.Transformer.from_crs(cs_from, cs_to)
        cs_to_from_tr = pyproj.Transformer.from_crs(cs_to, cs_from)

        logger.info(f'Drawing coordinate system. - ({cs_to.name})')

        if not cs_to.is_projected:
            raise ProgressError('Želeni koordinatni sistem mora biti projeciran.')

        # Do not draw grid lines near black pixels in the map
        def should_draw_grid_line(x0, y0, line_dir):
            (x0, y0) = map_to_grid(x0, y0)
            
            # check 3 wide area += 10 dir around the point for dark pixels (black or near black)
            if line_dir == 'x':
                for x in range(x0 - 2, x0 + 3):
                    if x < 0 or x >= grid_img.size[0]:
                        continue
                    for y in range(y0 - 10, y0 + 10):
                        if y < 0 or y >= grid_img.size[1]:
                            continue
                        col = grid_img.getpixel((x, y))
                        if col[0] < 20 and col[1] < 20 and col[2] < 20:
                            return False
            else:
                for x in range(x0 - 10, x0 + 10):
                    if x < 0 or x >= grid_img.size[0]:
                        continue
                    for y in range(y0 - 2, y0 + 3):
                        if y < 0 or y >= grid_img.size[1]:
                            continue
                        col = grid_img.getpixel((x, y))
                        if col[0] < 20 and col[1] < 20 and col[2] < 20:
                            return False

            return True

        auto_darken = True
        # DTK25 has baked in grid lines, so we just repaint them
        if raster_type == dto.RasterType.DTK25:
            auto_darken = False

        # Draw grid lines on the map
        def draw_grid_line(x0, y0, x1, y1, line_dir):
            x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
            gx0, gy0 = map_to_grid(x0, y0)
            gx1, gy1 = map_to_grid(x1, y1)
            if line_dir == 'x':
                assert(abs(gx0 - gx1) <= 1)
                if max(gx0, gx1) >= grid_img.size[0] or min(gx0, gx1) < 0:
                    return # skip line if it is outside the grid
                for y in range(int(y0), int(y1)):
                    if not auto_darken or should_draw_grid_line(x0, y, line_dir):
                        map_draw.line((x0, y, x0 + 1, y), fill='black')
                    else:
                        # Darken the pixel
                        col = grid_img.getpixel(map_to_grid(x0, y))
                        col = (max(0, col[0] - 90), max(0, col[1] - 90), max(0, col[2] - 90))              
                        map_draw.line((x0, y, x0 + 1, y), fill=col)

            elif line_dir == 'y':
                assert(abs(gy0 - gy1) <= 1)
                if max(gy0, gy1) >= grid_img.size[1] or min(gy0, gy1) < 0:
                    return # skip line if it is outside the grid
                for x in range(int(x0), int(x1)):
                    if not auto_darken or should_draw_grid_line(x, y0, line_dir):
                        map_draw.line((x, y0, x, y0 + 1), fill='black')
                    else:
                        # Darken the pixel
                        col = grid_img.getpixel(map_to_grid(x, y0))
                        col = (max(0, col[0] - 90), max(0, col[1] - 90), max(0, col[2] - 90))
                        map_draw.line((x, y0, x, y0 + 1), fill=col)

        superscript_map = {
            "0": "", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}

        grid_edge_ws = grid_to_world_tr.xy(grid_img.size[1], 0)
        grid_edge_en = grid_to_world_tr.xy(0, grid_img.size[0])

        # Convert to target coordinate system
        grid_edge_ws = cs_from_to_tr.transform(grid_edge_ws[0], grid_edge_ws[1])
        grid_edge_en = cs_from_to_tr.transform(grid_edge_en[0], grid_edge_en[1])

        grid_edge_ws_grid = (math.ceil(grid_edge_ws[0] / 1000) * 1000, math.ceil(grid_edge_ws[1] / 1000) * 1000)
        grid_edge_en_grid = (math.floor(grid_edge_en[0] / 1000 + 1) * 1000, math.floor(grid_edge_en[1] / 1000 + 1) * 1000)

        pt.step(0.5)
        for x in range(int(grid_edge_ws_grid[0]), int(grid_edge_en_grid[0]), 1000):
            xline_s = map_to_world_tr.colrow(*cs_to_from_tr.transform(x, grid_edge_ws[1]))
            xline_n = map_to_world_tr.colrow(*cs_to_from_tr.transform(x, grid_edge_en[1]))
            if not skip_grid_lines:
                draw_grid_line(xline_n[0], xline_n[1], xline_s[0], xline_s[1] - 1, 'x')
            cord = f'{int(x):06}'
            if x == grid_edge_ws_grid[0] or x == grid_edge_en_grid[0] - 1000:
                txt = f'{superscript_map[cord[-6]]}{cord[-5:-3]}'
            else:
                txt = f'{cord[-5:-3]}'
            map_draw.text((xline_s[0], xline_s[1] + 5), txt, fill='black', align='center', anchor='mt', font=grid_font)
            map_draw.text((xline_n[0], xline_n[1] - 5), txt, fill='black', align='center', anchor='ms', font=grid_font)

        pt.step(0.6)
        for y in range(int(grid_edge_ws_grid[1]), int(grid_edge_en_grid[1]), 1000):
            yline_w = map_to_world_tr.colrow(*cs_to_from_tr.transform(grid_edge_ws[0], y))
            yline_e = map_to_world_tr.colrow(*cs_to_from_tr.transform(grid_edge_en[0], y))
            if not skip_grid_lines:
                draw_grid_line(yline_w[0], yline_w[1], yline_e[0] - 1, yline_e[1], 'y')
            cord = f'{int(y):06}'
            if y == grid_edge_ws_grid[1] or y == grid_edge_en_grid[1] - 1000:
                txt = f'{superscript_map[cord[-6]]}{cord[-5:-3]}'
            else:
                txt = f'{cord[-5:-3]}'
            map_draw.text((yline_w[0] - 5, yline_w[1]), txt, fill='black', align='center', anchor='rm', font=grid_font)
            map_draw.text((yline_e[0] + 5, yline_e[1]), txt, fill='black', align='center', anchor='lm', font=grid_font)

        border_bottom_px = grid_font.getbbox('⁸88')[3] + 5
    else:
        logger.info('Skipping coordinate system drawing.')
        pt.step(0.6)
    
    # Draw the edge of the map in WGS84
    if edge_wgs84:
        pt.step(0.7)
        logger.info('Drawing WGS84 edge.')
        # Outer edge
        border_margins = [px*1.1 for px in grid_font.getbbox('⁸88')][2:]
        wgs_border = (grid_border[0] - border_margins[0], grid_border[1] - border_margins[1], grid_border[2] + border_margins[0], grid_border[3] + border_margins[1])
        map_draw.rectangle(wgs_border, outline='black', width=2)

        # Extend inner edge to the border
        map_draw.line((grid_border[0], wgs_border[1], grid_border[0], wgs_border[3]), fill='black', width=2)
        map_draw.line((grid_border[2], wgs_border[1], grid_border[2], wgs_border[3]), fill='black', width=2)
        map_draw.line((wgs_border[0], grid_border[1], wgs_border[2], grid_border[1]), fill='black', width=2)
        map_draw.line((wgs_border[0], grid_border[3], wgs_border[2], grid_border[3]), fill='black', width=2)

        def a4_draw_text_rotate(xy, xof, yof, text, angle, font):
            # Draw text with rotation
            size = font.getbbox(text)
            text_img = Image.new('RGBA', (size[2] - size[0], size[3] - size[1]), 0)
            text_draw = ImageDraw.Draw(text_img)
            text_draw.text((0, 0), text, font=font, anchor='lt', fill='black')
            text_img = text_img.rotate(angle, expand=True)
            map_img.paste(text_img, (int(xy[0] + xof * text_img.width), int(xy[1] + yof * text_img.height)), text_img)

        crs_from = pyproj.CRS.from_epsg(3794)
        crs_to = pyproj.CRS.from_epsg(4326)
        wgs_tr = pyproj.Transformer.from_crs(crs_from, crs_to)
        d96_tr = pyproj.Transformer.from_crs(crs_to, crs_from)

        txt_lat = lambda lat: f'φ = {deg_to_deg_min_sec(lat)}'
        txt_lon = lambda lon: f'λ = {deg_to_deg_min_sec(lon)}'

        # Show NW corner
        wgs_nw = wgs_tr.transform(*grid_to_world_tr.xy(0, 0))
        a4_draw_text_rotate((wgs_border[0] - 5, grid_border[1]), -1, 0, txt_lat(wgs_nw[0]), 90, grid_font)
        map_draw.text((grid_border[0], wgs_border[1] - 5), txt_lon(wgs_nw[1]), fill='black', align='center', anchor='lb', font=grid_font)

        # Show NE corner
        wgs_ne = wgs_tr.transform(*grid_to_world_tr.xy(0, grid_img.size[0]))
        a4_draw_text_rotate((wgs_border[2] + 5, grid_border[1]), 0, 0, txt_lat(wgs_ne[0]), -90, grid_font)
        map_draw.text((grid_border[2], wgs_border[1] - 5), txt_lon(wgs_ne[1]), fill='black', align='center', anchor='rb', font=grid_font)

        # Show SE corner
        wgs_se = wgs_tr.transform(*grid_to_world_tr.xy(grid_img.size[1], grid_img.size[0]))
        a4_draw_text_rotate((wgs_border[2] + 5, grid_border[3]), 0, -1, txt_lat(wgs_se[0]), -90, grid_font)
        map_draw.text((grid_border[2], wgs_border[3] + 5), txt_lon(wgs_se[1]), fill='black', align='center', anchor='rt', font=grid_font)

        # Show SW corner
        wgs_sw = wgs_tr.transform(*grid_to_world_tr.xy(grid_img.size[1], 0))
        a4_draw_text_rotate((wgs_border[0] - 5, grid_border[3]), -1, -1, txt_lat(wgs_sw[0]), 90, grid_font)
        map_draw.text((grid_border[0], wgs_border[3] + 5), txt_lon(wgs_sw[1]), fill='black', align='center', anchor='lt', font=grid_font)

        pt.step(0.9)
        # Show NW - NE minute markers
        avg_lat_n = (wgs_nw[0] + wgs_ne[0]) / 2
        sec_we_n = (math.ceil(wgs_nw[1] * 60), math.floor(wgs_ne[1] * 60))
        for sec in range(sec_we_n[0], sec_we_n[1] + 1):
            xy = map_to_world_tr.colrow(*d96_tr.transform(avg_lat_n, sec / 60))
            map_draw.line((xy[0], wgs_border[1], xy[0], wgs_border[1] + border_margins[1] * 0.5), fill='black', width=2)

        # Show SE - NE minute markers
        avg_lon_e = (wgs_ne[1] + wgs_se[1]) / 2
        sec_sn_e = (math.ceil(wgs_se[0] * 60), math.floor(wgs_ne[0] * 60))
        for sec in range(sec_sn_e[0], sec_sn_e[1] + 1):
            xy = map_to_world_tr.colrow(*d96_tr.transform(sec / 60, avg_lon_e))
            map_draw.line((wgs_border[2], xy[1], wgs_border[2] - border_margins[0] * 0.5, xy[1]), fill='black', width=2)

        # Show SW - SE minute markers
        avg_lat_s = (wgs_sw[0] + wgs_se[0]) / 2
        sec_we_s = (math.ceil(wgs_sw[1] * 60), math.floor(wgs_se[1] * 60))
        for sec in range(sec_we_s[0], sec_we_s[1] + 1):
            xy = map_to_world_tr.colrow(*d96_tr.transform(avg_lat_s, sec / 60))
            map_draw.line((xy[0], wgs_border[3], xy[0], wgs_border[3] - border_margins[1] * 0.5), fill='black', width=2)

        # Show SW - NW minute markers
        avg_lon_w = (wgs_sw[1] + wgs_nw[1]) / 2
        sec_sn_w = (math.ceil(wgs_sw[0] * 60), math.floor(wgs_nw[0] * 60))
        for sec in range(sec_sn_w[0], sec_sn_w[1] + 1):
            xy = map_to_world_tr.colrow(*d96_tr.transform(sec / 60, avg_lon_w))
            map_draw.line((wgs_border[0], xy[1], wgs_border[0] + border_margins[0] * 0.5, xy[1]), fill='black', width=2)

        pt.step(1)
        return real_to_map_tr.xy(0, wgs_border[3])[0]
    else:
        logger.info('Skipping WGS84 edge drawing.')
        pt.step(1)
        return real_to_map_tr.xy(0, grid_border[3] + border_bottom_px)[0]

def cp_name(i, cp: dto.ControlPointOptions, cp_count):
  if cp.name:
      return cp.name
  if i == 0:
      return 'START'
  if i == cp_count - 1 and cp.connect_next == False:
      return 'FINISH'
          
  return f'KT{i}'

def draw_control_points(map_img, map_to_world_tr, control_point_settings: dto.ControlPointsConfig, pt: ProgressTracker = NoProgress):
    cp_size_real = control_point_settings.cp_size
    control_points = control_point_settings.cps

    if len(control_points) == 0:
        logger.info('No control points to draw.')
        return

    logger.info(f'Drawing control points. ({len(control_points)} points)')

    map_supersample = 2
    cp_img = Image.new('RGBA', [int(p * map_supersample) for p in map_img.size], (0, 0, 0, 0))
    cp_draw = ImageDraw.Draw(cp_img)

    if control_point_settings.cp_font == dto.ControlPointFont.SERIF:
      cp_font = ImageFont.truetype('times.ttf', 60 * map_supersample)
    elif control_point_settings.cp_font == dto.ControlPointFont.SANS:
      cp_font = ImageFont.truetype('arial.ttf', 60 * map_supersample)
    else:
      raise ProgressError('Neveljavna pisava kontrolne točke')

    m_to_px = lambda m: m * TARGET_DPI / 0.0254 * map_supersample

    cp_lines_width_px = int(m_to_px(0.0004)) # Line width in m
    cp_size_px = cp_lines_width_px + m_to_px(cp_size_real) # Total size of the control point
    cp_dot_size_px = m_to_px(0.0003) # 0.3mm size 
    cp_line_start_offset = m_to_px(control_point_settings.cp_line_start_offset)

    cp_count = len(control_points)
    
    # Recalculate the names and positions of the control points
    for i, cp in enumerate(control_points):
        cp.name = cp_name(i, cp, cp_count)
        x, y = map_to_world_tr.colrow(cp.e, cp.n)
        x, y = x * map_supersample, y * map_supersample
        cp.x = x
        cp.y = y


    def next_cp(i):
        return control_points[(i + 1) % cp_count]
    
    def prev_cp(i):
        return control_points[(i - 1) % cp_count]
    
    def cp_radius(cp, theta):
        if cp.kind == dto.ControlPointKind.TRIANGLE:
            return (cp_size_px - cp_lines_width_px / 2) / (2 * math.cos(math.acos(math.sin(3*(theta + math.pi)))/3)) # Circumradius of a triangle
        elif cp.kind == dto.ControlPointKind.DOT:
            return cp_dot_size_px * 2 # Add some margin to the dot
        elif cp.kind == dto.ControlPointKind.POINT:
            return 0
        return cp_size_px
    
    def calculate_label_position(i, cp: dto.ControlPointOptions, outer_label_distance = 0.3 * cp_size_px):
        if cp_count <= 1:
            return cp.x, cp.y + cp_size_px + outer_label_distance, 'mt'
        
        cp_curr = cp
        
        if cp_count == 2: # Only 2 control points, use straight line
            cp_next = next_cp(i)
            bisector_x = cp_curr.x - cp_next.x
            bisector_y = cp_curr.y - cp_next.y

            # Normalize the bisector
            bisector_len = math.sqrt(bisector_x**2 + bisector_y**2)
            if bisector_len == 0:
                return cp.x, cp.y + cp_size_px + outer_label_distance, 'mt'
        else: # More than 2 control points, calculate bisector
            cp_prev = prev_cp(i)
            cp_next = next_cp(i)
            
            # Calculate vectors from current CP to previous and next CPs
            vec_to_prev = (cp_prev.x - cp_curr.x, cp_prev.y - cp_curr.y)
            vec_to_next = (cp_next.x - cp_curr.x, cp_next.y - cp_curr.y)
            
            # Normalize vectors
            prev_len = math.sqrt(vec_to_prev[0]**2 + vec_to_prev[1]**2)
            next_len = math.sqrt(vec_to_next[0]**2 + vec_to_next[1]**2)
            
            if prev_len == 0 or next_len == 0:
                return cp.x, cp.y + cp_size_px + outer_label_distance, 'mt'
            
            prev_norm = (vec_to_prev[0]/prev_len, vec_to_prev[1]/prev_len)
            next_norm = (vec_to_next[0]/next_len, vec_to_next[1]/next_len)
            
            # Sum the normalized vectors and negate to get the outside bisector
            bisector_x = -(prev_norm[0] + next_norm[0])
            bisector_y = -(prev_norm[1] + next_norm[1])
            
            # Normalize the bisector
            bisector_len = math.sqrt(bisector_x**2 + bisector_y**2)
            if bisector_len == 0:
                # If the bisector is zero length (straight line), use perpendicular
                bisector_x = -next_norm[1]
                bisector_y = next_norm[0]
                bisector_len = 1.0
            
        bisector_x /= bisector_len
        bisector_y /= bisector_len
        
        angle = math.degrees(math.atan2(-bisector_y, bisector_x))

        # Calculate label position at a distance from the control point
        label_distance = cp_radius(cp, math.atan2(bisector_y, bisector_x)) + outer_label_distance
        label_x = cp.x + bisector_x * label_distance
        label_y = cp.y + bisector_y * label_distance

        # Determine anchor based on direction and kind of the control point
        if cp.kind == dto.ControlPointKind.TRIANGLE:
            # Determine anchor based on which side of the triangle the label is on
            # Cornes of the triangle are top, diagonal left, diagonal right
            if angle >= -150 and angle <= -30:
                anchor = 'mt'
            elif angle < -150 or angle > 90:
                anchor = 'rb'
            else:
                anchor = 'lb'
        else:
            # Determine anchor based on 8 directional segments
            if -22.5 <= angle <= 22.5:         # East
                anchor = 'lm'
            elif 22.5 < angle <= 67.5:         # North-East
                anchor = 'lb'
            elif 67.5 < angle <= 112.5:        # North
                anchor = 'mb'
            elif 112.5 < angle <= 157.5:       # North-West
                anchor = 'rb'
            elif angle > 157.5 or angle <= -157.5:  # West
                anchor = 'rm'
            elif -157.5 < angle <= -112.5:     # South-West
                anchor = 'rt'
            elif -112.5 < angle <= -67.5:      # South
                anchor = 'mt'
            elif -67.5 < angle <= -22.5:       # South-East
                anchor = 'lt'
            else:
                # Fallback (should not happen)
                anchor = 'mm'
        
        return int(label_x), int(label_y), anchor
    
    def draw_triangle_cp(x, y, col):
        cp_draw.polygon([
            (x, y - cp_size_px),
            (x + cp_size_px * math.cos(math.radians(30)), y + cp_size_px * math.sin(math.radians(30))),
            (x - cp_size_px * math.cos(math.radians(30)), y + cp_size_px * math.sin(math.radians(30))),
        ], outline=col, width=cp_lines_width_px)

    
    def draw_circle_cp(x, y, col):
        cp_draw.ellipse(
            (x - cp_size_px, y - cp_size_px,
             x + cp_size_px, y + cp_size_px),
             outline=col, width=cp_lines_width_px)
        
    def draw_line(from_cp: dto.ControlPointOptions, to_cp: dto.ControlPointOptions):
        if to_cp.kind == dto.ControlPointKind.SKIP:
            return

        theta = math.atan2(to_cp.y - from_cp.y, to_cp.x - from_cp.x)
        theta_rev = theta - math.pi

        from_radius = cp_radius(from_cp, theta) + cp_line_start_offset
        to_radius = cp_radius(to_cp, theta_rev) + cp_line_start_offset
        cp_distance = math.sqrt((from_cp.x - to_cp.x) ** 2 + (from_cp.y - to_cp.y) ** 2)
        
        if from_radius + to_radius > cp_distance:
            # If the distance is too small, do not draw the line
            return

        from_x = from_cp.x + from_radius * math.cos(theta)
        from_y = from_cp.y + from_radius * math.sin(theta)
        to_x = to_cp.x - to_radius * math.cos(theta)
        to_y = to_cp.y - to_radius * math.sin(theta)

        cp_draw.line((from_x, from_y, to_x, to_y), fill=from_cp.color_line, width=cp_lines_width_px)

    def draw_name(x, y, anchor, name, color):
        if control_point_settings.cp_name_shadow:
            # Create a blurred shadow of the text
            text_size = cp_font.getbbox(name, anchor='lt')
            blur_radius = 30
            img_blur = Image.new('L', (text_size[2] + blur_radius * 2, text_size[3] + blur_radius * 2))
            draw_blur = ImageDraw.Draw(img_blur)
            draw_blur.text((blur_radius, blur_radius), name, fill='white', font=cp_font, anchor='lt')
            img_blur = img_blur.filter(ImageFilter.GaussianBlur(blur_radius/2))
            dst_box = cp_font.getbbox(name, anchor=anchor)
            img_shadow = Image.new('L', img_blur.size, 128)
            cp_img.paste(img_shadow, (int(x - blur_radius + dst_box[0]), int(y - blur_radius + dst_box[1])), mask=img_blur)

        # Draw the text
        cp_draw.text((x, y), name, fill=color, align='center', anchor=anchor, font=cp_font)

    for i, cp in pt.over_range(0, 0.5, enumerate(control_points)):
        if cp.kind == dto.ControlPointKind.SKIP:
            continue

        x, y = cp.x, cp.y

        # middle dot
        if cp.kind != dto.ControlPointKind.POINT:
          cp_draw.ellipse(
              (x - cp_dot_size_px, y - cp_dot_size_px, x + cp_dot_size_px, y + cp_dot_size_px),
              fill=cp.color)
        
        if cp.connect_next and cp_count > 1:
            draw_line(cp, next_cp(i))

        if cp.kind == dto.ControlPointKind.TRIANGLE:
            draw_triangle_cp(x, y, cp.color)
        elif cp.kind == dto.ControlPointKind.CIRCLE:
            draw_circle_cp(x, y, cp.color)
        elif cp.kind == dto.ControlPointKind.DOT:
            pass
        else:
            logger.warning(f'Unknown control point kind: {cp.kind}')

        label_x, label_y, anchor = calculate_label_position(i, cp)
        draw_name(label_x, label_y, anchor, cp.name, cp.color)

    # Downsample the control points image
    cp_img = cp_img.resize(map_img.size)
    pt.step(0.75)

    # Draw the control points on the map
    map_img.paste(cp_img, (0, 0), cp_img)

    pt.step(1)

def draw_markings(map_img, bbox, naslov1, naslov2, dodatno, slikal, slikad, epsg, edge_wgs84, target_scale, raster_source, real_to_map_tr, pt: ProgressTracker = NoProgress):
    map_draw = ImageDraw.Draw(map_img)
    
    title_font = ImageFont.truetype('times.ttf', 60)
    scale_font = ImageFont.truetype('timesi.ttf', 24)
    map_info_font = ImageFont.truetype('timesi.ttf', 28)

    pt.step(0)

    # Draw the title
    logger.info(f'Drawing title. {naslov1} {naslov2}')
    title_w = 0

    if naslov1 and naslov2:
        title_p0 = list(real_to_map_tr.colrow((bbox[0] + bbox[2]) / 2, bbox[3]))
        title_txt = [
            f'{naslov1}',
            f'{naslov2}'
        ][::-1]
        for txt in title_txt:
            map_draw.text(title_p0, txt, fill='black', align='center', anchor='mb', font=title_font)
            title_bbox = title_font.getbbox(txt)
            title_p0[1] -= title_bbox[3]
            title_w = max(title_w, title_bbox[2] - title_bbox[0])
    else:
        naslov = f'{naslov1}{naslov2}'
        title_p0 = list(real_to_map_tr.colrow((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2))
        map_draw.text(title_p0, naslov, fill='black', align='center', anchor='mm', font=title_font)
        title_bbox = title_font.getbbox(naslov)
        title_w = title_bbox[2] - title_bbox[0]

    pt.step(0.1)
    # Draw the logos
    logo_margin = 30
    logo_scale = 0.8
    bbox_size = real_to_map_tr.colrow(bbox[2] - bbox[0], bbox[3] - bbox[1])

    if slikal:
        logger.info(f'Drawing left logo: {slikal}')
        try:
            logo_l = Image.open(slikal)
        except Image.UnidentifiedImageError as e:
            raise ProgressError(f'Leva slika ni v podprtem formatu.') from e

        logo_l.thumbnail((bbox_size[1] * logo_scale, bbox_size[1] * logo_scale))
        logo_p0 = (
            int(title_p0[0] - title_w / 2 - logo_l.size[0] - logo_margin),
            int(real_to_map_tr.colrow(0, bbox[1])[1] + (bbox_size[1] - logo_l.size[1]) / 2)
        )
        if logo_l.mode == 'RGBA':
            map_img.paste(logo_l, logo_p0, logo_l)
        else:
            map_img.paste(logo_l, logo_p0)

    if slikad:
        logger.info(f'Drawing right logo: {slikad}')
        try:
            logo_d = Image.open(slikad)
        except Image.UnidentifiedImageError as e:
            raise ProgressError(f'Desna slika ni v podprtem formatu.') from e
        logo_d.thumbnail((bbox_size[1] * logo_scale, bbox_size[1] * logo_scale))
        logo_p0 = (
            int(title_p0[0] + title_w / 2 + logo_margin),
            int(real_to_map_tr.colrow(0, bbox[1])[1] + (bbox_size[1] - logo_d.size[1]) / 2)
        )
        if logo_d.mode == 'RGBA':
            map_img.paste(logo_d, logo_p0, logo_d)
        else:
            map_img.paste(logo_d, logo_p0)

    pt.step(0.3)

    # Draw the scale
    scale_max_size = 0.05 # 5 cm
    # Find the largest scale that fits the map:
    # 5m, 10m, 20m, 50m, 100m, 200m, 500m, 1km, 2km, 5km, 10km, 20km, 50km, 100km, 200km, 500km, 1000km
    scale_sizes = [5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000][::-1]
    scale_size = next((s for s in scale_sizes if s / target_scale <= scale_max_size), None)

    if scale_size is None:
        scale_size = scale_max_size * target_scale

    logger.info(f'Drawing scale. ({scale_size}m)')

    # Scale position
    scale_height = scale_font.getbbox('0')[3]
    scale_length = scale_size / target_scale
    scale_line_p0 = real_to_map_tr.colrow(bbox[0], bbox[3])
    scale_line_p1 = real_to_map_tr.colrow(bbox[0] + scale_length, bbox[3])

    # Main scale line
    map_draw.line((*scale_line_p0, *scale_line_p1), fill='black', width=2)
    map_draw.line((*scale_line_p0, scale_line_p0[0], scale_line_p0[1] - scale_height), fill='black', width=2)
    map_draw.line((*scale_line_p1, scale_line_p1[0], scale_line_p1[1] - scale_height), fill='black', width=2)
    
    # Scale text
    scale_txt = lambda s: f'{s}m' if s < 1000 else f'{s//1000}km'
    map_draw.text((scale_line_p0[0], scale_line_p0[1] - scale_height - 5), scale_txt(0), fill='black', align='center', anchor='lb', font=scale_font)
    map_draw.text((scale_line_p1[0], scale_line_p1[1] - scale_height - 5), scale_txt(scale_size), fill='black', align='center', anchor='rb', font=scale_font)

    # Scale markings
    for i in range(1, 20):
        scale_line_p = real_to_map_tr.colrow(bbox[0] + i * scale_length / 20, bbox[3])
        i_scale_height = scale_height / 2
        if i % 2 == 0:
            i_scale_height *= 1.2
        if i % 5 == 0:
            i_scale_height *= 1.5
        map_draw.line((*scale_line_p, scale_line_p[0], scale_line_p[1] - i_scale_height), fill='black', width=2)

    pt.step(0.5)
    # Map info
    logger.info('Drawing map info.')
    def get_coord_system_name():
        if epsg == 'Brez':
            if edge_wgs84:
                return 'WGS84:4326'
            return 'Brez'
        extra = ''
        if edge_wgs84:
            extra = ', WGS84:4326'

        crs = pyproj.CRS.from_epsg(int(epsg.split(':')[1]))

        crs_epsg = crs.to_epsg()
        if crs_epsg == 3794:
            return f'D96/TM:3794{extra}'
        elif crs_epsg == 3912:
            return f'D48/GK:3912{extra}'
        elif crs_epsg == 8687:
            return f'D96/UTM33N:8687{extra}'
        elif crs_epsg == 32633:
            return f'WGS84/UTM33N:32633{extra}'
        else:
            return f'{crs.name}:{crs.to_epsg()}{extra}'

    ekvidistanca = {
        'dtk50': '20m',
        'dtk25': '10m',
        'dtk10': '10m',
        'dtk5': '5m',
        'otm': '10m',
        'osm': 'Brez',
        '': 'Brez'
    }[raster_source]

    map_info_txt = [
        f'Koord. sistem: {get_coord_system_name()}',
        f'Merilo: 1:{int(target_scale)}',
        f'Ekvidistanca: {ekvidistanca}',
    ][::-1]
    
    map_info_p0 = [scale_line_p1[0] + 10, scale_line_p1[1]]
    for txt in map_info_txt:
        map_draw.text(map_info_p0, txt, anchor='lb', fill='black', align='left', font=map_info_font)
        map_info_p0[1] -= map_info_font.getbbox(txt)[3]

    pt.step(0.8)
    vir = {
        'dtk50': 'Državna topografska karta 1:50.000',
        'dtk25': 'Državna topografska karta 1:25.000',
        'dtk10': 'Državna topografska karta 1:10.000',
        'dtk5': 'Državna topografska karta 1:5.000',
        'otm': 'OpenTopoMap',
        'osm': 'OpenStreetMap',
        '': 'Topograf'
    }[raster_source]
    vir_attr = {
        'dtk50': 'Geodetska uprava RS, 2023',
        'dtk25': 'Geodetska uprava RS, 1996',
        'dtk10': 'Geodetska uprava RS, 1994',
        'dtk5': 'Geodetska uprava RS, 1994',
        'otm': 'OpenTopoMap (CC-BY-SA)',
        'osm': 'OpenStreetMap (CC-BY-SA)',
        '': 'Rod Jezerska ščuka'
    }[raster_source]

    map_source_txt = [
        f'Vir: {vir}',
        f'© {vir_attr}; Ustvarjeno s topograf.scuke.si',
        f'{dodatno}'
    ][::-1]
    map_source_p0 = list(real_to_map_tr.colrow(bbox[2], bbox[3]))
    # map_source_p0[1] = scale_line_p1[1]
    for txt in map_source_txt:
        map_draw.text(map_source_p0, txt, anchor='rb', fill='black', align='right', font=map_info_font)
        map_source_p0[1] -= map_info_font.getbbox(txt)[3]

    pt.step(1)
        
def get_preview_image(bounds, epsg, raster_type, raster_source, zoom_adjust, preview_width_m, preview_height_m, pt: ProgressTracker = NoProgress):
    target_size = (
        int(preview_width_m * TARGET_DPI / 0.0254),
        int(preview_height_m * TARGET_DPI / 0.0254)
    )
    pt.msg('Pridobivanje podatkov')
    if raster_source != '':
        grid_raster = get_raster_map(raster_type, raster_source, zoom_adjust, bounds, pt.sub(0, 0.9))
        grid_img = Image.fromarray(rasterio.plot.reshape_as_image(grid_raster), 'RGB')
        grid_img = grid_img.resize(target_size, Image.Resampling.LANCZOS)
    else:
        grid_img = Image.new('RGB', target_size, 0xFFFFFF)
        logger.info(f'Created blank raster map. ({target_size})')
        pt.step(0.9)

    # Draw coordinate system
    if epsg != 'Brez':
        pt.msg('Risanje mreže')
        grid_draw = ImageDraw.Draw(grid_img)
        grid_font = ImageFont.truetype('timesbi.ttf', 48)
        grid_to_world_tr = rasterio.transform.AffineTransformer(rasterio.transform.from_bounds(*bounds, *grid_img.size))
        grid_to_world_tr.colrow = lambda x, y: grid_to_world_tr.rowcol(x, y)[::-1]
        cs_from = pyproj.CRS.from_epsg(3794)
        cs_to = pyproj.CRS.from_epsg(int(epsg.split(':')[1]))
        cs_from_to_tr = pyproj.Transformer.from_crs(cs_from, cs_to)
        cs_to_from_tr = pyproj.Transformer.from_crs(cs_to, cs_from)

        logger.info(f'Drawing coordinate system. - ({cs_to.name})')

        if not cs_to.is_projected:
            raise ValueError('The target coordinate system must be projected.')

        superscript_map = {
            "0": "", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}

        grid_edge_ws = grid_to_world_tr.xy(grid_img.size[1], 0)
        grid_edge_en = grid_to_world_tr.xy(0, grid_img.size[0])

        # Convert to target coordinate system
        grid_edge_ws = cs_from_to_tr.transform(grid_edge_ws[0], grid_edge_ws[1])
        grid_edge_en = cs_from_to_tr.transform(grid_edge_en[0], grid_edge_en[1])

        grid_edge_ws_grid = (math.ceil(grid_edge_ws[0] / 1000) * 1000, math.ceil(grid_edge_ws[1] / 1000) * 1000)
        grid_edge_en_grid = (math.floor(grid_edge_en[0] / 1000 + 1) * 1000, math.floor(grid_edge_en[1] / 1000 + 1) * 1000)

        for x in range(int(grid_edge_ws_grid[0]), int(grid_edge_en_grid[0]), 1000):
            xline_s = grid_to_world_tr.colrow(*cs_to_from_tr.transform(x, grid_edge_ws[1]))
            xline_n = grid_to_world_tr.colrow(*cs_to_from_tr.transform(x, grid_edge_en[1]))
            grid_draw.line([xline_n, xline_s], fill='black')
            cord = f'{int(x):06}'
            txt = f'{superscript_map[cord[-6]]}{cord[-5:-3]}'
            grid_draw.text(xline_s, txt, fill='red', align='center', anchor='lb', font=grid_font)
            grid_draw.text(xline_n, txt, fill='red', align='center', anchor='lt', font=grid_font)

        for y in range(int(grid_edge_ws_grid[1]), int(grid_edge_en_grid[1]), 1000):
            yline_w = grid_to_world_tr.colrow(*cs_to_from_tr.transform(grid_edge_ws[0], y))
            yline_e = grid_to_world_tr.colrow(*cs_to_from_tr.transform(grid_edge_en[0], y))
            cord = f'{int(y):06}'
            txt = f'{superscript_map[cord[-6]]}{cord[-5:-3]}'
            grid_draw.text(yline_w, txt, fill='red', align='center', anchor='lb', font=grid_font)
            grid_draw.text(yline_e, txt, fill='red', align='center', anchor='rb', font=grid_font)
            grid_draw.line([yline_w, yline_e], fill='black')
    else:
        logger.info('Skipping coordinate system drawing.')

    pt.step(1)
    return grid_img

class DMV:
    xyz_e0 = 364629 # Easting of the origin point in the DMV system
    xyz_n0 = 25485 # Northing of the origin point in the DMV system
    tile_e = 2250 # Size of the (minor) tile in the DMV system
    tile_n = 3000 # Size of the (minor) tile in the DMV system
    tiles_e = 10 # Number of minor tiles a major tile has in the easting direction
    tiles_n = 5 # Number of minor tiles a major tile has in the northing direction
    step_size = 12.5 # Resolution of the grid
    tile_max_e = int(tile_e / step_size) # Number of steps in the major tile
    tile_max_n = int(tile_n / step_size) # Number of steps in the minor tile

    # Caching
    loaded_bounds = None # Loaded bounds for the DMV tiles [folder, bounds]
    loaded_file = None # Loaded DMV125 file [bounds, readlines]

def dmv_tile_bounds(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()
        first_line = lines[0].strip()
        last_line = lines[-1].strip()
        parts = first_line.split(' ')
        e_min = float(parts[0])
        n_min = float(parts[1])
        parts = last_line.split(' ')
        e_max = float(parts[0])
        n_max = float(parts[1])
        return e_min, n_min, e_max, n_max

def dmv_get_bounds(dmv125_folder):
    if DMV.loaded_bounds is not None:
        if DMV.loaded_bounds[0] == dmv125_folder:
            return DMV.loaded_bounds[1]

    cache_index = get_cache_index({'dmv125_folder': dmv125_folder})
    cache_file = os.path.join(get_cache_dir('tile_bounds'), f'{cache_index}-bounds-cache.json')
    if os.path.exists(cache_file) and USE_CACHE:
        with open(cache_file, 'r') as f:
            return json.load(f)

    logger.info('Calculating DMV tile bounds.')
    bounds = {}
    xyz_tiles = [fn for fn in os.listdir(dmv125_folder) if fn.endswith('.XYZ')]
    for fn in xyz_tiles:
        bounds[fn] = dmv_tile_bounds(os.path.join(dmv125_folder, fn))

    # Save the bounds to the cache
    if USE_CACHE:
        with open(cache_file, 'w') as f:
            json.dump(bounds, f)

    DMV.loaded_bounds = (dmv125_folder, bounds)

    logger.info('DMV tile bounds calculated.')
    return bounds

def dmv_coord_to_tile(e, n):
    """
    Convert easting and northing coordinates to DMV tile coordinates.
    This can be wrong on the edges of the tiles (+-5m).
    """
    e -= DMV.xyz_e0
    n -= DMV.xyz_n0
    global_e = int(e / DMV.tile_e)
    global_n = int(n / DMV.tile_n)
    major_e, minor_e = divmod(global_e, DMV.tiles_e)
    major_n, minor_n = divmod(global_n, DMV.tiles_n)
    major_e = chr(ord("A") + major_e)
    major_n = major_n + 19
    tile_i = (DMV.tiles_n -1 - minor_n) * DMV.tiles_e + minor_e + 1
    return major_e, major_n, tile_i

def dmv_tile_to_fn(major_e, major_n, tile_i):
    return f'VT{major_e}{major_n:02d}{tile_i:02d}.XYZ'

def dmv_is_inside_tile(e, n, tile_bounds):
    """
    Check if the easting and northing coordinates are inside the tile bounds.
    """
    return tile_bounds[0] <= e <= tile_bounds[2] and tile_bounds[1] <= n <= tile_bounds[3]


def dmv_coord_to_tile_checked(e, n, dmv125_folder):
    """
    Convert easting and northing coordinates to DMV tile coordinates.
    This checks if the tile exists in the dmv125 folder and makes sure .
    """
    major_e, major_n, tile_i = dmv_coord_to_tile(e, n)
    bounds = dmv_get_bounds(dmv125_folder)
    tile_fn = dmv_tile_to_fn(major_e, major_n, tile_i)
    if tile_fn in bounds:
        tile_bounds = bounds[tile_fn]
        if dmv_is_inside_tile(e, n, tile_bounds):
            return tile_fn, tile_bounds

    # Tile does not exist or we have experienced an edge case (see dmv_coord_to_tile)
    # We need to check all tiles in the folder to find the one that contains the point
    for fn, tile_bounds in bounds.items():
        if dmv_is_inside_tile(e, n, tile_bounds):
            major_e = fn[2]
            major_n = int(fn[3:5])
            tile_i = int(fn[5:7])
            return fn, tile_bounds
        
    return None, None

def dmv_get_height(tile_lines, bounds, e, n):
    """
    Get the height from the DMV125 file.
    """
    min_e, min_n = bounds[0], bounds[1]
    e -= min_e
    n -= min_n
    e_idx = round(e / DMV.step_size)
    n_idx = round(n / DMV.step_size)
    e_idx = int(max(min(e_idx, DMV.tile_max_e), 0))
    n_idx = int(max(min(n_idx, DMV.tile_max_n), 0))
    line_idx = n_idx * (DMV.tile_max_e + 1) + e_idx
    line = tile_lines[line_idx].strip()
    parts = line.split(' ')
    e_actual = float(parts[0])
    n_actual = float(parts[1])
    h = float(parts[-1])
    if abs(e + min_e - e_actual) > 7 or abs(n + min_n - n_actual) > 7:
        raise ValueError(f"Coordinates {e}, {n} are not inside the tile bounds {bounds}.")
    return h
    
def get_world_height(dmv125_folder, e, n):
    """
    Get the world height from the DMV125 file.
    """
    if DMV.loaded_file is not None:
        if dmv_is_inside_tile(e, n, DMV.loaded_file[0]):
            return dmv_get_height(DMV.loaded_file[1], DMV.loaded_file[0], e, n)
        
    tile_fn, tile_bounds = dmv_coord_to_tile_checked(e, n, dmv125_folder)
    if tile_fn is None:
        return 0
    
    with open(os.path.join(dmv125_folder, tile_fn), 'r') as f:
        lines = f.readlines()
        DMV.loaded_file = (tile_bounds, lines)

        return dmv_get_height(lines, tile_bounds, e, n)

def create_control_point_report(control_point_settings: dto.ControlPointsConfig, raster_type, raster_folder, title, dmv125_folder, output_file, pt: ProgressTracker = NoProgress):
    cps = control_point_settings.cps
    cp_count = len(cps)
    pt.step(0)
    if cp_count == 0:
        logger.info('No control points to draw.')
        pt.step(1)
        return

    # Compute the grid size
    cp_grid_size_m = (
      CP_REPORT_PAGE_SIZE_M[0] - CP_REPORT_PAGE_MARGIN_M[0] - CP_REPORT_PAGE_MARGIN_M[2],
      CP_REPORT_PAGE_SIZE_M[1] - CP_REPORT_PAGE_MARGIN_M[1] - CP_REPORT_PAGE_MARGIN_M[3]
    )
    cp_report_page_size_px = (
        int(CP_REPORT_PAGE_SIZE_M[0] * TARGET_DPI / 0.0254),
        int(CP_REPORT_PAGE_SIZE_M[1] * TARGET_DPI / 0.0254)
    )
    cp_grid_cell_size_m = (
        cp_grid_size_m[0] / CP_REPORT_GRID_SIZE[0],
        cp_grid_size_m[1] / CP_REPORT_GRID_SIZE[1]
    )
    cp_grid_cell_size_px = (
        int(cp_grid_cell_size_m[0] * TARGET_DPI / 0.0254),
        int(cp_grid_cell_size_m[1] * TARGET_DPI / 0.0254)
    )
    cp_grid_cells_per_page = CP_REPORT_GRID_SIZE[0] * CP_REPORT_GRID_SIZE[1]
    cp_preview_size_px = (
        min(cp_grid_cell_size_px) - 10,
        min(cp_grid_cell_size_px) - 10
    )

    def cp_index_to_page(i):
        return i // cp_grid_cells_per_page

    def cp_index_to_pos(i):
        i = i % cp_grid_cells_per_page
        return (
            (CP_REPORT_PAGE_MARGIN_M[0] + (i % CP_REPORT_GRID_SIZE[0]) * cp_grid_cell_size_m[0]) * TARGET_DPI / 0.0254,
            (CP_REPORT_PAGE_MARGIN_M[1] + (i // CP_REPORT_GRID_SIZE[0]) * cp_grid_cell_size_m[1]) * TARGET_DPI / 0.0254
        )
    
    pages: list[Image.Image] = []
    draws: list[ImageDraw.ImageDraw] = []
    for _ in range(math.ceil(len(cps) / cp_grid_cells_per_page)):
        pages.append(Image.new('RGB', cp_report_page_size_px, 'white'))
        draws.append(ImageDraw.Draw(pages[-1]))

    cp_font = ImageFont.truetype('times.ttf', 60)
    cs_from = pyproj.CRS.from_epsg(3794)
    cs_to = pyproj.CRS.from_epsg(4326)
    cs_from_to_tr = pyproj.Transformer.from_crs(cs_from, cs_to)
    txt_line_h_px = cp_font.getbbox('0')[3] + 5

    def draw_cp_report(i, cp, draw: ImageDraw.ImageDraw, pos):
      # Create square for cp report
      draw.rectangle(
          (pos[0], pos[1], pos[0] + cp_grid_cell_size_px[0], pos[1] + cp_grid_cell_size_px[1]),
          outline='black', width=2
      )

      # Convert to WGS84
      cp_wgs = cs_from_to_tr.transform(cp.e, cp.n)
      cp_wgs_formated = [ deg_to_deg_min_sec(c, 2) for c in cp_wgs ]

      cp_text = [
          f'KT: {cp_name(i, cp, cp_count)}',
          f'N: {cp.n:.3f}',
          f'E: {cp.e:.3f}',
          f'φ: {cp_wgs_formated[0]}',
          f'λ: {cp_wgs_formated[1]}',
          f'φ: {cp_wgs[0]:.6f}',
          f'λ: {cp_wgs[1]:.6f}'
      ]

      # Draw text
      for txti, txt in enumerate(cp_text):
          draw.text((pos[0] + 5, pos[1] + 5 + txti * txt_line_h_px), txt, fill='black', font=cp_font)

      # Get the preview image
      if raster_folder != '':
        cp_preview_bounds = (
            cp.e - CP_REPORT_PREVIEW_SIZE_RADIUS_M,
            cp.n - CP_REPORT_PREVIEW_SIZE_RADIUS_M,
            cp.e + CP_REPORT_PREVIEW_SIZE_RADIUS_M,
            cp.n + CP_REPORT_PREVIEW_SIZE_RADIUS_M
        )
        cp_preview_raster = get_raster_map(raster_type, raster_folder, 1, cp_preview_bounds)
        cp_preview_img = Image.fromarray(rasterio.plot.reshape_as_image(cp_preview_raster), 'RGB')
        cp_preview_img = cp_preview_img.resize(cp_preview_size_px)

        # Draw centering cross
        cp_draw = ImageDraw.Draw(cp_preview_img, 'RGBA')
        cp_draw.line((cp_preview_size_px[0] // 2, 0, cp_preview_size_px[0] // 2, cp_preview_size_px[1]), fill='#f00b', width=3)
        cp_draw.line((0, cp_preview_size_px[1] // 2, cp_preview_size_px[0], cp_preview_size_px[1] // 2), fill='#f00b', width=3)

        # Paste the preview image
        pages[cp_index_to_page(i)].paste(cp_preview_img, (int(pos[0] + cp_grid_cell_size_px[0] - cp_preview_size_px[0] - 5), int(pos[1] + 5)))
    
    for i, cp in pt.over_range(0.1, 0.9, enumerate(cps)):
        page = cp_index_to_page(i)
        pos = cp_index_to_pos(i)
        draw_cp_report(i, cp, draws[page], pos)

    title_pos = cp_index_to_pos(1)
    title_pos = (title_pos[0], title_pos[1] - 10)
    draws[0].text(title_pos, f'Kontrolne točke - {title}', fill='black', font=cp_font, anchor='mb')

    # Create timeline page if we have multiple points
    if cp_count > 1:
        pt.msg('Ustvarjanje časovnice')
        timeline_page = create_timeline_page(cps, title, dmv125_folder, cp_report_page_size_px)
        pages.insert(0, timeline_page)

    pages[0].save(output_file, save_all=True, append_images=pages[1:], dpi=(TARGET_DPI, TARGET_DPI), author=PDF_AUTHOR)
    pt.step(1)

def calculate_distance(cp1, cp2):
    """Calculate the direct distance between two control points in meters."""
    return math.sqrt((cp2.e - cp1.e) ** 2 + (cp2.n - cp1.n) ** 2)

def create_timeline_page(cps, title, dmv125_folder, page_size_px):
    logger.info('Creating timeline report page')
    timeline_page = Image.new('RGB', page_size_px, 'white')
    draw = ImageDraw.Draw(timeline_page)
    
    # Fonts for the timeline page
    title_font = ImageFont.truetype('times.ttf', 80)
    header_font = ImageFont.truetype('timesbd.ttf', 60)
    text_font = ImageFont.truetype('times.ttf', 50)
    small_font = ImageFont.truetype('times.ttf', 40)
    
    # Draw title
    title_text = f"Časovnica poti - {title}"
    draw.text((page_size_px[0]/2, 100), title_text, fill='black', font=title_font, anchor='mt')
    
    # Calculate distances and heights
    cp_count = len(cps)
    distances = []
    heights = []
    height_gains = [0 for _ in range(cp_count)]
    height_losses = [0 for _ in range(cp_count)]

    # Distances
    for i, cp in enumerate(cps):
        heights.append(get_world_height(dmv125_folder, cp.e, cp.n))
        if i == cp_count - 1 and not cp.connect_next:
            distances.append(0)
        else:
            distances.append(calculate_distance(cp, cps[(i + 1) % cp_count]))

    total_distance = sum(distances)

    height_samples = 1000
    height_sample_step = max(total_distance / height_samples, 20) # Minimum step size of 20m

    profile_height = []
    profile_distance = []
    curr_dist = 0
    last_height = heights[0]
    stat_idx = 0

    # Height profile
    for i, cp in enumerate(cps):
        if i == cp_count - 1 and not cps[i].connect_next:
            break

        next_cp = cps[(i + 1) % cp_count]
        dist = distances[i]
        current_leg_dist = 0
        for _ in range(int(dist / height_sample_step) + 1):
            ratio = current_leg_dist / dist
            sample_e = cp.e + ratio * (next_cp.e - cp.e)
            sample_n = cp.n + ratio * (next_cp.n - cp.n)

            sample_height = get_world_height(dmv125_folder, sample_e, sample_n)
            profile_height.append(sample_height)
            profile_distance.append(curr_dist + current_leg_dist)

            # Calculate height gain/loss
            height_diff = sample_height - last_height
            if height_diff > 0:
                height_gains[stat_idx] += height_diff
            else:
                height_losses[stat_idx] += -height_diff
            last_height = sample_height
            stat_idx = i # Index must always lag for one step
            current_leg_dist += height_sample_step
        curr_dist += dist

    # Create the height profile graph
    plt.figure(figsize=(8, 4), dpi=TARGET_DPI)
    plt.subplots_adjust(left=0.08, right=0.95, top=0.9, bottom=0.2)
    
    # Plot the continuous height profile
    plt.plot(profile_distance, profile_height, 'b-', linewidth=2)
    
    energy = max(profile_height) - min(profile_height)
    label_height = energy * 0.03

    # Add points for each checkpoint
    current_dist = 0
    for i, cp in enumerate(cps):
        plt.scatter(current_dist, heights[i], c='red', s=50, zorder=5)
        plt.text(current_dist, heights[i] + label_height, cp_name(i, cp, cp_count), 
                 fontsize=8, ha='center', va='bottom', rotation=45)
        current_dist += distances[i]
    
    if cps[-1].connect_next:
        plt.scatter(current_dist, heights[0], c='red', s=50, zorder=5)
        plt.text(current_dist, heights[0] + label_height, cp_name(0, cps[0], cp_count), 
                 fontsize=8, ha='center', va='bottom', rotation=45)

    # Set labels and grid
    plt.xlabel('Razdalja [km]')
    plt.ylabel('Nadmorska višina [m]')
    plt.title('Višinski profil poti')
    plt.grid(True, linestyle='--', alpha=0.7)
    
    # Format x-axis as km
    plt.gca().xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x/1000:.1f}'))
    
    # Force integer y-axis ticks
    plt.gca().yaxis.set_major_locator(MaxNLocator(integer=True))
    
    # Save the plot to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    
    # Create an image from the buffer
    height_profile = Image.open(buf)
    
    # Paste the height profile onto the page
    timeline_page.paste(height_profile, (int((page_size_px[0] - height_profile.width) / 2), 220))
    
    # Create statistics table
    table_top = 220 + height_profile.height + 50
    table_left = 100
    table_right = page_size_px[0] - 100
    table_row_height = 60
    
    # Draw table header
    headers = ["Točka", "Razdalja", "Vzpon", "Spust", "V. razlika", "Čas hoje"]
    col_widths = [0.20, 0.15, 0.15, 0.15, 0.15, 0.20]  # Width percentages
    table_width = table_right - table_left
    
    # Draw table headers
    draw.rectangle((table_left, table_top, table_right, table_top + table_row_height), 
                   outline='black', width=2, fill='#EEEEEE')
    
    x_pos = table_left
    for i, header in enumerate(headers):
        col_width = col_widths[i] * table_width
        draw.text((x_pos + col_width/2, table_top + table_row_height/2), 
                  header, fill='black', font=header_font, anchor='mm')
        draw.line((x_pos + col_width, table_top, x_pos + col_width, 
                   table_top + table_row_height * (len(cps) + 2)), fill='black', width=1)
        x_pos += col_width
    
    if cps[-1].connect_next:
        cps.append(cps[0]) # Add the first checkpoint again for the last row
        heights.append(heights[0])
        cp_count += 1
        total_height_diff = 0
    else:
        total_height_diff = int(heights[-1] - heights[0])

    # Draw data rows
    for i, cp in enumerate(cps):
        row_top = table_top + table_row_height * (i + 1)
        
        # Draw row background
        draw.rectangle((table_left, row_top, table_right, row_top + table_row_height), 
                       outline='black', width=1)
        
        # Calculate values for this checkpoint
        name = cp_name(i, cp, cp_count)
        
        segment_distance = distances[i - 1] if i > 0 else 0
        height_gain = height_gains[i - 1] if i > 0 else 0
        height_loss = height_losses[i - 1] if i > 0 else 0
            
        # Calculate walking time (in minutes)
        # Formula: 4 km = 60 min; 400 m gain = 60 min; 800 m loss = 60 min
        time_distance = (segment_distance / 4000) * 60  # minutes for distance
        time_gain = (height_gain / 400) * 60  # minutes for ascent
        time_loss = (height_loss / 800) * 60  # minutes for descent
        walking_time = time_distance + time_gain + time_loss
        
        # Format time as hours:minutes
        hours = int(walking_time // 60)
        minutes = int(walking_time % 60)
        time_str = f"{hours} h {minutes:02d} min" if hours > 0 else f"{minutes} min"
            
        # Format heights
        height_diff_str = f"{int(heights[i] - heights[i-1])}" if i > 0 else "0"
        
        # Values to display in each column
        values = [
            name,
            f"{int(segment_distance)} m",
            f"{int(height_gain)} m",
            f"{int(height_loss)} m",
            f"{height_diff_str} m",
            time_str
        ]
        
        # Draw values
        x_pos = table_left
        for j, value in enumerate(values):
            col_width = col_widths[j] * table_width
            draw.text((x_pos + col_width/2, row_top + table_row_height/2), 
                      value, fill='black', font=text_font, anchor='mm')
            x_pos += col_width
    
    # Draw total row
    total_row_top = table_top + table_row_height * (cp_count + 1)
    draw.rectangle((table_left, total_row_top, table_right, total_row_top + table_row_height), 
                   outline='black', width=2, fill='#EEEEEE')
    
    # Calculate total walking time
    total_gain = sum(height_gains)
    total_loss = sum(height_losses)
    total_time = (total_distance / 4000) * 60 + (total_gain / 400) * 60 + (total_loss / 800) * 60
    total_hours = int(total_time // 60)
    total_minutes = int(total_time % 60)
    total_time_str = f"{total_hours}:{total_minutes:02d} h" if total_hours > 0 else f"{total_minutes} min"

    # Format total distance
    if total_distance >= 1000:
        total_distance_str = f"{total_distance/1000:.1f} km"
    else:
        total_distance_str = f"{int(total_distance)} m"
    
    # Values for the total row
    total_values = [
        "SKUPAJ",
        total_distance_str,
        f"{int(total_gain)} m",
        f"{int(total_loss)} m",
        f"{int(total_height_diff)} m",
        total_time_str
    ]
    
    # Draw total values
    x_pos = table_left
    for j, value in enumerate(total_values):
        col_width = col_widths[j] * table_width
        draw.text((x_pos + col_width/2, total_row_top + table_row_height/2), 
                  value, fill='black', font=header_font, anchor='mm')
        x_pos += col_width
    
    # Add a footer note about the calculation method
    footer_text = "Časi hoje so izračunani po pravilniku za ROT: 4 km = 1h; 400 m vzpona = 1h; 800 m spusta = 1h" \
                "\nOpozorilo: Časovnica uporablja višinsko razliko glede na ravno linijo, ne optimalno pot! " \
                "\nVišinski podatki: © Geodetska uprava RS, Digitalni model višin 12,5m, 2017"
    draw.text((page_size_px[0]/2, page_size_px[1] - 75), 
              footer_text, fill='black', font=small_font, anchor='mm', align='center')
    
    return timeline_page

def create_map(r: dto.MapCreateRequest, pt: ProgressTracker = NoProgress):
    # Temp folder
    output_file = os.path.join(get_cache_dir(f'maps/{r.id}'), 'map.pdf')
    output_conf = os.path.join(get_cache_dir(f'maps/{r.id}'), 'conf.json')
    output_cp_report = os.path.join(get_cache_dir(f'maps/{r.id}'), 'cp_report.pdf')
    output_thumbnail = os.path.join(get_cache_dir(f'maps/{r.id}'), 'thumbnail.webp')

    logger.info(f'Creating map: {r.id} - {r.naslov1} {r.naslov2}')

    if os.path.exists(output_file) and USE_CACHE:
        pt.step(1)
        logger.info(f'Map exists (nothing to do). - ({output_file})')
        return
    
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    pt.msg('Pridobivanje podatkov')
    map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, map_to_grid = get_grid_and_map((r.map_size_w_m, r.map_size_h_m), (r.map_w, r.map_s, r.map_e, r.map_n), r.raster_type, r.raster_source, r.zoom_adjust, pt.sub(0, 0.3))

    pt.msg('Risanje mreže')
    skip_grid_lines = r.raster_type == dto.RasterType.DTK25
    border_bottom = draw_grid(map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, r.raster_type, r.epsg, r.edge_wgs84, map_to_grid, skip_grid_lines, pt.sub(0.3, 0.5))

    if len(r.control_points.cps) > 0:
        pt.msg('Risanje KT')
        draw_control_points(map_img, map_to_world_tr, r.control_points, pt.sub(0.5, 0.7))
        cp_title = f'{r.naslov1} {r.naslov2}'
        pt.msg('Izdelava poročila KT')
        create_control_point_report(r.control_points, r.raster_type, r.raster_source, cp_title, r.dmv125_folder, output_cp_report, pt.sub(0.7, 0.8))

    markings_bbox = (
        GRID_MARGIN_M[3],
        float(border_bottom),
        r.map_size_w_m - GRID_MARGIN_M[1],
        r.map_size_h_m - 0.005
    )

    pt.msg('Risanje oznak')
    draw_markings(map_img, markings_bbox, r.naslov1, r.naslov2, r.dodatno, r.slikal, r.slikad, r.epsg, r.edge_wgs84, r.target_scale, r.raster_type, real_to_map_tr, pt.sub(0.8, 0.9))

    logger.info(f'Saving map to: {output_file}')
    pt.msg('Izdelava predogleda karte')
    thumbnail = map_img.copy()
    thumbnail.thumbnail((1024, 1024))
    thumbnail.save(output_thumbnail)
    
    # Save the map using img2pdf (PIL uses JPEG compression for PDFs)
    with tempfile.TemporaryFile() as tf:
        pt.msg('Optimizacija karte')
        map_img.save(tf, format='png', dpi=(TARGET_DPI, TARGET_DPI), optimize=True)
        pt.step(0.95)
        tf.seek(0)
        pt.msg('Shranjevanje karte')
        with open(output_file, 'wb') as f:
            f.write(img2pdf.convert(
                tf,
                title=r.naslov1,
                subject=r.naslov2,
                author=PDF_AUTHOR,
                producer=f'Topograf {r.id}'
            ))
    
    # Save the configuration (remove full paths)
    r.output_folder = os.path.basename(r.output_folder)
    r.raster_source = os.path.basename(r.raster_source)
    if not r.raster_source.startswith('https://'):
        r.raster_source = os.path.basename(r.raster_source)
    r.slikal = os.path.basename(r.slikal)
    r.slikad = os.path.basename(r.slikad)
    with open(output_conf, 'w') as f:
        f.write(r.model_dump_json())
    pt.step(1)
    pt.msg('Končano')

def map_preview(r: dto.MapPreviewRequest, pt: ProgressTracker = NoProgress):
    logger.info(f'Creating map preview. ({r.map_w}, {r.map_s}, {r.map_e}, {r.map_n}, {r.epsg}, {r.raster_source})')
    bounds = (r.map_w, r.map_s, r.map_e, r.map_n)
    
    preview_size_m = (
        r.map_size_w_m - GRID_MARGIN_M[1] - GRID_MARGIN_M[3],
        r.map_size_h_m - GRID_MARGIN_M[0] - GRID_MARGIN_M[2]
    )

    grid_img = get_preview_image(bounds, r.epsg, r.raster_type, r.raster_source, r.zoom_adjust, *preview_size_m, pt.sub(0, 0.9))

    output_file = os.path.join(get_cache_dir('map_previews'), f'{r.id}.png')

    pt.msg('Shranjevanje predogleda')
    grid_img.save(output_file, dpi=(TARGET_DPI, TARGET_DPI))
    pt.step(1)
    pt.msg('Končano')

def store_error(request: dto.MapBaseRequest, e: Exception, argv: list[str]):
    error_file = os.path.join(get_cache_dir('errors'), f'{request.id}.json')

    with open(error_file, 'w') as f:
        f.write(json.dumps({
            'timestamp': datetime.datetime.now().isoformat(),
            'type': type(e).__name__,
            'error': str(e),
            'args': argv,
            'traceback': traceback.format_exc().splitlines(),
          }, indent=2))

def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    if len(sys.argv) == 1 and INPUT_CONTEXT is not None:
        with open(INPUT_CONTEXT, 'r') as f:
            error = json.load(f)
        logger.warning(f'Recovering from error: {error["type"]} - {error["error"]}')
        argv = error["args"]
        for f, t in error.get('replace', []):
            argv = [arg.replace(f, t) for arg in argv]
        sys.argv = [sys.argv[0]] + argv

    logger.info(f'Arguments: {sys.argv[1:]}')
    cm_args = dto.parse_command_line_args()
    request = dto.create_request_from_args(cm_args)

    global OUTPUT_DIR
    OUTPUT_DIR = request.output_folder
    print(f'Output dir: {OUTPUT_DIR}')

    if cm_args.get('emit_progress'):
        logger.info('Progress tracking enabled.')
        def on_progress(progress: float):
            print(f'PROGRESS: {progress:02.2f}', file=sys.stderr)
        def on_message(message: str):
            print(f'MESSAGE: {message}', file=sys.stderr)
        pt = ProgressTracker(0, 100, on_progress, on_message)
    else:
        pt = NoProgress

    try:
        if request.request_type == dto.RequestType.CREATE_MAP:
            create_map(request, pt)
        elif request.request_type == dto.RequestType.MAP_PREVIEW:
            map_preview(request, pt)
        else:
            raise ValueError(f'Unknown request type: {request.request_type}')
    except ProgressError as e:
        logger.error(e)
        logger.error(traceback.format_exc())
        if cm_args.get('emit_progress'):
            print(f'ERROR: {str(e)}', file=sys.stderr)
        store_error(request, e, sys.argv)
        exit(1)
    except Exception as e:
        logger.error(e)
        logger.error(traceback.format_exc())
        if cm_args.get('emit_progress'):
            print(f'ERROR: Interna napaka ({pt.last_msg()})', file=sys.stderr)
        store_error(request, e, sys.argv)
        exit(1)

if __name__ == '__main__':
    main()
    exit(0)
