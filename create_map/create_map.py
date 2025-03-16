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
import dto
import img2pdf

### STATIC CONFIGURATION ###

# General settings
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

def get_raster_map_bounds(raster_folder: str):
    """
    Returns the bounds of the rasters inside the folder as a dictionary with the filename as the key.

    Parameters
    ----------
    raster_folder : str
        The folder containing the raster files.
    """
    folder_hash = get_cache_index({'raster_folder': os.path.abspath(raster_folder)})
    bounds_cache_fn = os.path.join(get_cache_dir(), f'{folder_hash}-bounds-cache.json')

    if os.path.exists(bounds_cache_fn) and USE_CACHE:
        with open(bounds_cache_fn, 'r') as f:
            bounds = json.load(f)
            logger.info(f'Using cached raster bounds. - ({folder_hash})')
            return bounds

    raster_files = [f for f in os.listdir(raster_folder) if f.endswith(".tif")]
    bounds = {}
    for filename in raster_files:
        fp = os.path.join(raster_folder, filename)
        with rasterio.open(fp) as src:
            bounds[filename] = [*src.bounds]

    with open(bounds_cache_fn, 'w') as f:
        json.dump(bounds, f)

    logger.info(f'Discovered raster bounds. - ({folder_hash})')
    return bounds

def get_raster_map_tiles(tiles_url: str, bounds: tuple[float]):
    """
    Gets the raster map from a tile server.
    
    Parameters
    ----------
    tiles_url : str
        The URL of the tile server.
    bounds : tuple (west, south, east, north)
        The bounds of the area to be merged. EPSG:3794
    """

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
        mosaic_web, extent_web = contextily.bounds2img(*bounds_3857, source=tiles_url, zoom_adjust=1)
        # Warp the tiles to EPSG:3794
        mosaic_d96, extent_d96 = contextily.warp_tiles(mosaic_web, extent_web, 'EPSG:3794', rasterio.enums.Resampling.lanczos)

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
                dst.write(rasterio.plot.reshape_as_raster(mosaic_d96))
            with memfile.open() as src:
                return rasterio.merge.merge([src], bounds)[0]
    except Exception as e:
        raise ValueError(f'Failed to get raster map tiles: {e}')

def get_raster_map(raster_type: dto.RasterType, raster_folder: str, bounds: tuple[float]):
    """
    Merges all the raster files in the folder that intersect with the given bounds.

    Parameters
    ----------
    raster_folder : str
        The folder containing the raster files.
    bounds : tuple (west, south, east, north)
        The bounds of the area to be merged. EPSG:3794
    """

    bounds_hash = get_cache_index({'raster_folder': os.path.abspath(raster_folder), 'bounds': bounds})
    raster_cache_fn = os.path.join(get_cache_dir('raster'), f'{bounds_hash}.npy')

    if os.path.exists(raster_cache_fn) and USE_CACHE:
        mosaic = np.load(raster_cache_fn)
        logger.info(f'Using cached raster mosaic. - ({bounds_hash} - {mosaic.shape})')
        return mosaic

    if raster_folder.startswith('https://'):
        mosaic = get_raster_map_tiles(raster_folder, bounds)
        np.save(raster_cache_fn, mosaic)
        logger.info(f'Created raster mosaic. - ({bounds_hash} - {mosaic.shape})')
        return mosaic
    
    crs_from = pyproj.CRS.from_epsg(3794)

    if raster_type == dto.RasterType.DTK25:
        crs_to = pyproj.CRS.from_epsg(3912)
        max_files = 6
    elif raster_type == dto.RasterType.DTK50:
        crs_to = pyproj.CRS.from_epsg(3794)
        max_files = 4
    else:
        raise ValueError('Invalid raster type.')
    
    transformer = pyproj.Transformer.from_crs(crs_from, crs_to)
    west, south = transformer.transform(bounds[0], bounds[1])
    east, north = transformer.transform(bounds[2], bounds[3])
    bounds = (west, south, east, north)

    raster_bounds = get_raster_map_bounds(raster_folder)
    selected_files = []
    bbox = shapely.geometry.box(*bounds)
    for filename, file_bounds in raster_bounds.items():
        file_bbox = shapely.geometry.box(*file_bounds)
        if bbox.intersects(file_bbox):
            selected_files.append(os.path.join(raster_folder, filename))

    if len(selected_files) == 0:
        raise ValueError('No raster files intersect with the given bounds.')
    
    if len(selected_files) > max_files:
        raise ValueError('Too many raster files intersect with the given bounds. Please select a smaller area.')

    src_files_to_mosaic = []
    for fp in selected_files:
        src = rasterio.open(fp)
        src_files_to_mosaic.append(src)
    
    mosaic, _ = rasterio.merge.merge(src_files_to_mosaic, bounds=bounds)

    np.save(raster_cache_fn, mosaic)

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

def get_grid_and_map(map_size_m: tuple[float], map_bounds: tuple[float], raster_type: dto.RasterType, raster_folder: str):
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
        grid_raster = get_raster_map(raster_type, raster_folder, map_bounds)
        grid_img = Image.fromarray(rasterio.plot.reshape_as_image(grid_raster), 'RGB').resize(grid_size_px, resample=Image.Resampling.LANCZOS)
    else:
        logger.info('Skipping raster map.')
        grid_img = Image.new('RGB', grid_size_px, 0xFFFFFF)

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
    
    return map_img, grid_img, add_colrow_to_transformer(map_to_world_tr), add_colrow_to_transformer(grid_to_world_tr), add_colrow_to_transformer(real_to_map_tr), map_to_grid


def draw_grid(map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, raster_type, epsg, edge_wgs84, map_to_grid):
    map_draw = ImageDraw.Draw(map_img)
    
    # Draw grid on the map
    logger.info('Drawing grid.')
    map_img.paste(grid_img, real_to_map_tr.colrow(GRID_MARGIN_M[3], GRID_MARGIN_M[0]))

    # Draw grid border
    logger.info('Drawing grid border.')
    border0 = map_to_world_tr.colrow(*grid_to_world_tr.xy(-1, -1))
    grid_border = (border0[0], border0[1], border0[0] + grid_img.size[0] + 1, border0[1] + grid_img.size[1] + 1)
    map_draw.rectangle(grid_border, outline='black', width=2)

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
            raise ValueError('The target coordinate system must be projected.')

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
            if line_dir == 'x':
                assert(abs(x0 - x1) <= 1)
                for y in range(int(y0), int(y1)):
                    if not auto_darken or should_draw_grid_line(x0, y, line_dir):
                        map_draw.line((x0, y, x0 + 1, y), fill='black')
                    else:
                        # Darken the pixel
                        col = grid_img.getpixel(map_to_grid(x0, y))
                        col = (max(0, col[0] - 90), max(0, col[1] - 90), max(0, col[2] - 90))              
                        map_draw.line((x0, y, x0 + 1, y), fill=col)

            elif line_dir == 'y':
                assert(abs(y0 - y1) <= 1)
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

        for x in range(int(grid_edge_ws_grid[0]), int(grid_edge_en_grid[0]), 1000):
            xline_s = map_to_world_tr.colrow(*cs_to_from_tr.transform(x, grid_edge_ws[1]))
            xline_n = map_to_world_tr.colrow(*cs_to_from_tr.transform(x, grid_edge_en[1]))
            draw_grid_line(xline_n[0], xline_n[1], xline_s[0], xline_s[1] - 1, 'x')
            cord = f'{int(x):06}'
            if x == grid_edge_ws_grid[0] or x == grid_edge_en_grid[0] - 1000:
                txt = f'{superscript_map[cord[-6]]}{cord[-5:-3]}'
            else:
                txt = f'{cord[-5:-3]}'
            map_draw.text((xline_s[0], xline_s[1] + 5), txt, fill='black', align='center', anchor='mt', font=grid_font)
            map_draw.text((xline_n[0], xline_n[1] - 5), txt, fill='black', align='center', anchor='ms', font=grid_font)

        for y in range(int(grid_edge_ws_grid[1]), int(grid_edge_en_grid[1]), 1000):
            yline_w = map_to_world_tr.colrow(*cs_to_from_tr.transform(grid_edge_ws[0], y))
            yline_e = map_to_world_tr.colrow(*cs_to_from_tr.transform(grid_edge_en[0], y))
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
    
    # Draw the edge of the map in WGS84
    if edge_wgs84:
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

        return real_to_map_tr.xy(0, wgs_border[3])[0]
    else:
        logger.info('Skipping WGS84 edge drawing.')
        return real_to_map_tr.xy(0, grid_border[3] + border_bottom_px)[0]

def cp_name(i, cp: dto.ControlPointOptions, cp_count):
  if cp.name:
      return cp.name
  if i == 0:
      return 'START'
  if i == cp_count - 1 and cp.connect_next == False:
      return 'END'
          
  return f'KT{i}'

def draw_control_points(map_img, map_to_world_tr, control_point_settings: dto.ControlPointsConfig):
    cp_size_real = control_point_settings.cp_size
    control_points = control_point_settings.cps

    if len(control_points) == 0:
        logger.info('No control points to draw.')
        return

    logger.info(f'Drawing control points. ({len(control_points)} points)')

    map_supersample = 2
    cp_img = Image.new('RGBA', [int(p * map_supersample) for p in map_img.size], (0, 0, 0, 0))
    cp_draw = ImageDraw.Draw(cp_img)

    cp_font = ImageFont.truetype('times.ttf', 60 * map_supersample)

    m_to_px = lambda m: m * TARGET_DPI / 0.0254 * map_supersample

    cp_lines_width_px = int(m_to_px(0.0004)) # Line width in m
    cp_size_px = cp_lines_width_px + m_to_px(cp_size_real) # Total size of the control point
    cp_dot_size_px = m_to_px(0.0003) # 0.3mm size 

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

        from_x = from_cp.x + cp_radius(from_cp, theta) * math.cos(theta)
        from_y = from_cp.y + cp_radius(from_cp, theta) * math.sin(theta)
        to_x = to_cp.x - cp_radius(to_cp, theta_rev) * math.cos(theta)
        to_y = to_cp.y - cp_radius(to_cp, theta_rev) * math.sin(theta)

        cp_draw.line((from_x, from_y, to_x, to_y), fill=from_cp.color_line, width=cp_lines_width_px)

    def draw_name(x, y, anchor, name, color):
        # Create a blurred shadow of the text
        text_size = cp_font.getbbox(name, anchor='lt')
        blur_radius = 30
        img_blur = Image.new('L', (text_size[2] + blur_radius * 2, text_size[3] + blur_radius * 2))
        draw_blur = ImageDraw.Draw(img_blur)
        draw_blur.text((blur_radius, blur_radius), name, fill='white', font=cp_font, anchor='lt')
        img_blur = img_blur.filter(ImageFilter.GaussianBlur(blur_radius/2))
        dst_box = cp_font.getbbox(name, anchor=anchor)
        img_shadow = Image.new('L', img_blur.size, 128)
        cp_img.paste(img_shadow, (x - blur_radius + dst_box[0], y - blur_radius + dst_box[1]), mask=img_blur)

        # Draw the text
        cp_draw.text((x, y), name, fill=color, align='center', anchor=anchor, font=cp_font)

    for i, cp in enumerate(control_points):
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

    # Draw the control points on the map
    map_img.paste(cp_img, (0, 0), cp_img)


def draw_markings(map_img, bbox, naslov1, naslov2, dodatno, slikal, slikad, epsg, edge_wgs84, target_scale, raster_source, real_to_map_tr):
    map_draw = ImageDraw.Draw(map_img)
    
    title_font = ImageFont.truetype('times.ttf', 60)
    scale_font = ImageFont.truetype('timesi.ttf', 24)
    map_info_font = ImageFont.truetype('timesi.ttf', 28)


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

    # Draw the logos
    logo_margin = 30
    logo_scale = 0.8
    bbox_size = real_to_map_tr.colrow(bbox[2] - bbox[0], bbox[3] - bbox[1])

    if slikal:
        logger.info(f'Drawing left logo: {slikal}')
        logo_l = Image.open(slikal)
        logo_l.thumbnail((bbox_size[1] * logo_scale, bbox_size[1] * logo_scale))
        logo_p0 = (
            int(title_p0[0] - title_w / 2 - logo_l.size[0] - logo_margin),
            int(real_to_map_tr.colrow(0, bbox[1])[1] + (bbox_size[1] - logo_l.size[1]) / 2)
        )
        map_img.paste(logo_l, logo_p0, logo_l)

    if slikad:
        logger.info(f'Drawing right logo: {slikad}')
        logo_d = Image.open(slikad)
        logo_d.thumbnail((bbox_size[1] * logo_scale, bbox_size[1] * logo_scale))
        logo_p0 = (
            int(title_p0[0] + title_w / 2 + logo_margin),
            int(real_to_map_tr.colrow(0, bbox[1])[1] + (bbox_size[1] - logo_d.size[1]) / 2)
        )
        map_img.paste(logo_d, logo_p0, logo_d)


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

    vir = {
        'dtk50': 'Državna topografska karta 1:50.000',
        'dtk25': 'Državna topografska karta 1:25.000',
        'otm': 'OpenTopoMap',
        'osm': 'OpenStreetMap',
        '': 'Topograf'
    }[raster_source]
    vir_attr = {
        'dtk50': 'Geodetska uprava RS, 2023',
        'dtk25': 'Geodetska uprava RS, 1996',
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

        
def get_preview_image(bounds, epsg, raster_type, raster_source, preview_width_m, preview_height_m):
    target_size = (
        int(preview_width_m * TARGET_DPI / 0.0254),
        int(preview_height_m * TARGET_DPI / 0.0254)
    )
    if raster_source != '':
        grid_raster = get_raster_map(raster_type, raster_source, bounds)
        grid_img = Image.fromarray(rasterio.plot.reshape_as_image(grid_raster), 'RGB')
        grid_img = grid_img.resize(target_size, Image.Resampling.LANCZOS)
    else:
        grid_img = Image.new('RGB', target_size, 0xFFFFFF)
        logger.info(f'Created blank raster map. ({target_size})')

    # Draw coordinate system
    if epsg != 'Brez':
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


    return grid_img

def create_control_point_report(control_point_settings: dto.ControlPointsConfig, raster_type, raster_folder, title, output_file):
    cps = control_point_settings.cps
    cp_count = len(cps)
    if cp_count == 0:
        logger.info('No control points to draw.')
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
        cp_preview_raster = get_raster_map(raster_type, raster_folder, cp_preview_bounds)
        cp_preview_img = Image.fromarray(rasterio.plot.reshape_as_image(cp_preview_raster), 'RGB')
        cp_preview_img = cp_preview_img.resize(cp_preview_size_px)

        # Draw centering cross
        cp_draw = ImageDraw.Draw(cp_preview_img, 'RGBA')
        cp_draw.line((cp_preview_size_px[0] // 2, 0, cp_preview_size_px[0] // 2, cp_preview_size_px[1]), fill='#f00b', width=3)
        cp_draw.line((0, cp_preview_size_px[1] // 2, cp_preview_size_px[0], cp_preview_size_px[1] // 2), fill='#f00b', width=3)

        # Paste the preview image
        pages[cp_index_to_page(i)].paste(cp_preview_img, (int(pos[0] + cp_grid_cell_size_px[0] - cp_preview_size_px[0] - 5), int(pos[1] + 5)))
    
    for i, cp in enumerate(cps):
        page = cp_index_to_page(i)
        pos = cp_index_to_pos(i)
        draw_cp_report(i, cp, draws[page], pos)

    title_pos = cp_index_to_pos(1)
    title_pos = (title_pos[0], title_pos[1] - 10)
    draws[0].text(title_pos, title, fill='black', font=cp_font, anchor='mb')

    pages[0].save(output_file, save_all=True, append_images=pages[1:], dpi=(TARGET_DPI, TARGET_DPI), author=PDF_AUTHOR)

def create_map(r: dto.MapCreateRequest):
    # Temp folder
    output_file = os.path.join(get_cache_dir(f'maps/{r.id}'), 'map.pdf')
    output_conf = os.path.join(get_cache_dir(f'maps/{r.id}'), 'conf.json')
    output_cp_report = os.path.join(get_cache_dir(f'maps/{r.id}'), 'cp_report.pdf')
    output_thumbnail = os.path.join(get_cache_dir(f'maps/{r.id}'), 'thumbnail.webp')

    logger.info(f'Creating map: {r.id} - {r.naslov1} {r.naslov2}')

    if os.path.exists(output_file) and USE_CACHE:
        logger.info(f'Map exists (nothing to do). - ({output_file})')
        return
    
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, map_to_grid = get_grid_and_map((r.map_size_w_m, r.map_size_h_m), (r.map_w, r.map_s, r.map_e, r.map_n), r.raster_type, r.raster_source)

    border_bottom = draw_grid(map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, r.raster_type, r.epsg, r.edge_wgs84, map_to_grid)

    if len(r.control_points.cps) > 0:
        draw_control_points(map_img, map_to_world_tr, r.control_points)
        cp_title = f'Kontrolne točke - {r.naslov1} {r.naslov2}'
        create_control_point_report(r.control_points, r.raster_type, r.raster_source, cp_title, output_cp_report)

    markings_bbox = (
        GRID_MARGIN_M[3],
        float(border_bottom),
        r.map_size_w_m - GRID_MARGIN_M[1],
        r.map_size_h_m - 0.005
    )

    draw_markings(map_img, markings_bbox, r.naslov1, r.naslov2, r.dodatno, r.slikal, r.slikad, r.epsg, r.edge_wgs84, r.target_scale, r.raster_type, real_to_map_tr)

    logger.info(f'Saving map to: {output_file}')
    thumbnail = map_img.copy()
    thumbnail.thumbnail((1024, 1024))
    thumbnail.save(output_thumbnail)
    
    # Save the map using img2pdf (PIL uses JPEG compression for PDFs)
    with tempfile.TemporaryFile() as tf:
        map_img.save(tf, format='png', dpi=(TARGET_DPI, TARGET_DPI), optimize=True)
        tf.seek(0)
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

def map_preview(r: dto.MapPreviewRequest):
    logger.info(f'Creating map preview. ({r.map_w}, {r.map_s}, {r.map_e}, {r.map_n}, {r.epsg}, {r.raster_source})')
    bounds = (r.map_w, r.map_s, r.map_e, r.map_n)
    
    preview_size_m = (
        r.map_size_w_m - GRID_MARGIN_M[1] - GRID_MARGIN_M[3],
        r.map_size_h_m - GRID_MARGIN_M[0] - GRID_MARGIN_M[2]
    )

    grid_img = get_preview_image(bounds, r.epsg, r.raster_type, r.raster_source, *preview_size_m)

    output_file = os.path.join(get_cache_dir('map_previews'), f'{r.id}.png')

    grid_img.save(output_file, dpi=(TARGET_DPI, TARGET_DPI))


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    logger.info(f'Arguments: {sys.argv[1:]}')
    cm_args = dto.parse_command_line_args()
    request = dto.create_request_from_args(cm_args)

    global OUTPUT_DIR
    OUTPUT_DIR = request.output_folder
    print(f'Output dir: {OUTPUT_DIR}')

    if request.request_type == dto.RequestType.CREATE_MAP:
        create_map(request)
    elif request.request_type == dto.RequestType.MAP_PREVIEW:
        map_preview(request)
    else:
        logger.error(f'Unknown request type: {request}')
        exit(1)

if __name__ == '__main__':
    main()
    exit(0)
