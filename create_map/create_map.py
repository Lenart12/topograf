from PIL import Image, ImageDraw, ImageFont
import sys
import math
import json
import pyproj
import json
import itertools
import pyproj.transformer
import rasterio
import rasterio.merge
import rasterio.plot
import rasterio.transform
import shapely
import json
import base64
import os
import tempfile

### STATIC CONFIGURATION ###

TARGET_DPI = 318
GRID_MARGIN_M = [0.011, 0.0141, 0.0195, 0.0143] # Margin around the A4 paper in meters [top, right, bottom, left]

### /STATIC CONFIGURATION ###

def get_raster_map_bounds(dtk50_folder: str):
    """
    Returns the bounds of the rasters inside the folder as a dictionary with the filename as the key.

    Parameters
    ----------
    dtk50_folder : str
        The folder containing the raster files.
    """
    bounds_cache = os.path.join(tempfile.gettempdir(), 'dtk50-bounds-cache.json')
    if os.path.exists(bounds_cache):
        with open(bounds_cache, 'r') as f:
            return json.load(f)

    raster_files = [f for f in os.listdir(dtk50_folder) if f.endswith(".tif")]
    bounds = {}
    for filename in raster_files:
        fp = os.path.join(dtk50_folder, filename)
        with rasterio.open(fp) as src:
            bounds[filename] = [*src.bounds]

    with open(bounds_cache, 'w') as f:
        json.dump(bounds, f)

    return bounds

def get_raster_map(dtk50_folder: str, bounds: tuple[float]):
    """
    Merges all the raster files in the folder that intersect with the given bounds.

    Parameters
    ----------
    dtk50_folder : str
        The folder containing the raster files.
    bounds : tuple (west, south, east, north)
        The bounds of the area to be merged. EPSG:3794
    """

    dtk50_bounds = get_raster_map_bounds(dtk50_folder)
    selected_files = []
    bbox = shapely.geometry.box(*bounds)
    for filename, file_bounds in dtk50_bounds.items():
        file_bbox = shapely.geometry.box(*file_bounds)
        if bbox.intersects(file_bbox):
            selected_files.append(os.path.join(dtk50_folder, filename))

    if len(selected_files) == 0:
        raise ValueError('No raster files intersect with the given bounds.')

    src_files_to_mosaic = []
    for fp in selected_files:
        src = rasterio.open(fp)
        src_files_to_mosaic.append(src)
    
    mosaic, _ = rasterio.merge.merge(src_files_to_mosaic, bounds=bounds)
    return mosaic

def get_grid_and_map(map_size_m: tuple[float], map_bounds: tuple[float], dtk50_folder: str):
    """
    Returns the map image, the grid image, and the transformers for converting between the map and the world.

    Parameters
    ----------
    map_size_m : tuple (width, height)
        The size of the map in meters.
    map_bounds : tuple (west, south, east, north)
        The bounds of the map in EPSG:3794.
    dtk50_folder : str
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

    # Get the raster map
    grid_raster = get_raster_map(dtk50_folder, map_bounds)
    grid_margin_px = [int(m * target_pxpm) for m in GRID_MARGIN_M]
    grid_size_px = [map_size_px[0] - grid_margin_px[1] - grid_margin_px[3], map_size_px[1] - grid_margin_px[0] - grid_margin_px[2]]
    grid_img = Image.fromarray(rasterio.plot.reshape_as_image(grid_raster), 'RGB').resize(grid_size_px)

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
    
    return map_img, grid_img, add_colrow_to_transformer(map_to_world_tr), add_colrow_to_transformer(grid_to_world_tr), add_colrow_to_transformer(real_to_map_tr), map_to_grid


def draw_grid(map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, epsg, edge_wgs84, map_to_grid):
    map_draw = ImageDraw.Draw(map_img)
    
    # Draw grid on the map
    map_img.paste(grid_img, real_to_map_tr.colrow(GRID_MARGIN_M[3], GRID_MARGIN_M[0]))

    # Draw grid border
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

        # Draw grid lines on the map
        def draw_grid_line(x0, y0, x1, y1, line_dir):
            x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
            if line_dir == 'x':
                assert(x0 == x1)
                for y in range(int(y0), int(y1)):
                    if should_draw_grid_line(x0, y, line_dir):
                        map_draw.line((x0, y, x0 + 2, y), fill='black')
                    else:
                        # Darken the pixel
                        col = grid_img.getpixel(map_to_grid(x0, y))
                        col = (max(0, col[0] - 90), max(0, col[1] - 90), max(0, col[2] - 90))              
                        map_draw.line((x0, y, x0 + 2, y), fill=col)

            elif line_dir == 'y':
                assert(y0 == y1)
                for x in range(int(x0), int(x1)):
                    if should_draw_grid_line(x, y0, line_dir):
                        map_draw.line((x, y0, x, y0 + 2), fill='black')
                    else:
                        # Darken the pixel
                        col = grid_img.getpixel(map_to_grid(x, y0))
                        col = (max(0, col[0] - 90), max(0, col[1] - 90), max(0, col[2] - 90))
                        map_draw.line((x, y0, x, y0 + 2), fill=col)

        superscript_map = {
            "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}

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
            txt = f'{superscript_map[cord[-6]]}{cord[-5:-3]}'
            map_draw.text((xline_s[0], xline_s[1] + 5), txt, fill='black', align='center', anchor='mt', font=grid_font)
            map_draw.text((xline_n[0], xline_n[1] - 5), txt, fill='black', align='center', anchor='ms', font=grid_font)

        for y in range(int(grid_edge_ws_grid[1]), int(grid_edge_en_grid[1]), 1000):
            yline_w = map_to_world_tr.colrow(*cs_to_from_tr.transform(grid_edge_ws[0], y))
            yline_e = map_to_world_tr.colrow(*cs_to_from_tr.transform(grid_edge_en[0], y))
            draw_grid_line(yline_w[0], yline_w[1], yline_e[0] - 1, yline_e[1], 'y')
            cord = f'{int(y):06}'
            txt = f'{superscript_map[cord[-6]]}{cord[-5:-3]}'
            map_draw.text((yline_w[0] - 5, yline_w[1]), txt, fill='black', align='center', anchor='rm', font=grid_font)
            map_draw.text((yline_e[0] + 5, yline_e[1]), txt, fill='black', align='center', anchor='lm', font=grid_font)

        border_bottom_px = grid_font.getbbox('⁸88')[3] + 5
        
    # Draw the edge of the map in WGS84
    if edge_wgs84:
        # Outer edge
        border_margins = [px*1.1 for px in grid_font.getbbox('⁸88')][2:]
        wgs_border = (grid_border[0] - border_margins[0], grid_border[1] - border_margins[1], grid_border[2] + border_margins[0], grid_border[3] + border_margins[1])
        map_draw.rectangle(wgs_border, outline='black', width=2)

        # Extend inner edge to the border
        map_draw.line((grid_border[0], wgs_border[1], grid_border[0], wgs_border[3]), fill='black', width=2)
        map_draw.line((grid_border[2], wgs_border[1], grid_border[2], wgs_border[3]), fill='black', width=2)
        map_draw.line((wgs_border[0], grid_border[1], wgs_border[2], grid_border[1]), fill='black', width=2)
        map_draw.line((wgs_border[0], grid_border[3], wgs_border[2], grid_border[3]), fill='black', width=2)

        # Convert decimal degrees to DD°MM'SS" format
        def deg_to_deg_min_sec(deg):
            d = int(deg)
            m = int((deg - d) * 60)
            s = int((deg - d - m / 60) * 3600)
            return f'{d}°{m:02}\'{s:02}"'

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
        return real_to_map_tr.xy(0, grid_border[3] + border_bottom_px)[0]

def draw_markings(map_img, bbox, naslov1, naslov2, dodatno, slikal, slikad, epsg, edge_wgs84, target_scale, real_to_map_tr):
    map_draw = ImageDraw.Draw(map_img)
    
    title_font = ImageFont.truetype('times.ttf', 60)
    scale_font = ImageFont.truetype('timesi.ttf', 24)
    map_info_font = ImageFont.truetype('timesi.ttf', 28)


    # Draw the title
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
        logo_l = Image.open(slikal)
        logo_l.thumbnail((bbox_size[1] * logo_scale, bbox_size[1] * logo_scale))
        logo_p0 = (
            int(title_p0[0] - title_w / 2 - logo_l.size[0] - logo_margin),
            int(real_to_map_tr.colrow(0, bbox[1])[1] + (bbox_size[1] - logo_l.size[1]) / 2)
        )
        map_img.paste(logo_l, logo_p0, logo_l)

    if slikad:
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
    def get_coord_system_name():
        if epsg == 'Brez':
            if edge_wgs84:
                return 'WGS84:4326'
            return 'Brez'
        extra = ''
        if edge_wgs84:
            extra = ', WGS84:4326'

        crs = pyproj.CRS.from_epsg(int(epsg.split(':')[1]))

        match crs.to_epsg():
            case 3794:
                return f'D96/TM:3794{extra}'
            case 3912:
                return f'D48/GK:3912{extra}'
            case 8687:
                return f'D96/UTM33N:8687{extra}'
            case 32633:
                return f'WGS84/UTM33N:32633{extra}'

        return f'{crs.name}:{crs.to_epsg()}{extra}'

    map_info_txt = [
        f'Koord. sistem: {get_coord_system_name()}',
        f'Merilo: 1:{int(target_scale)}',
        f'Ekvidistanca: 10m',
    ][::-1]
    
    map_info_p0 = [scale_line_p1[0] + 10, scale_line_p1[1]]
    for txt in map_info_txt:
        map_draw.text(map_info_p0, txt, anchor='lb', fill='black', align='left', font=map_info_font)
        map_info_p0[1] -= map_info_font.getbbox(txt)[3]

    map_source_txt = [
        f'Vir: Državna topografska karta 1:50.000',
        f'© Geodetska uprava RS, 2023; Ustvarjeno s topograf.scuke.si',
        f'{dodatno}'
    ][::-1]
    map_source_p0 = list(real_to_map_tr.colrow(bbox[2], bbox[3]))
    # map_source_p0[1] = scale_line_p1[1]
    for txt in map_source_txt:
        map_draw.text(map_source_p0, txt, anchor='rb', fill='black', align='right', font=map_info_font)
        map_source_p0[1] -= map_info_font.getbbox(txt)[3]

        
def create_map(configuration):
    # Unpack the configuration
    map_size_w_m = configuration['map_size_w_m']
    map_size_h_m = configuration['map_size_h_m']
    map_w = configuration['map_w']
    map_s = configuration['map_s']
    map_e = configuration['map_e']
    map_n = configuration['map_n']
    target_scale = configuration['target_scale']
    naslov1 = configuration['naslov1']
    naslov2 = configuration['naslov2']
    dodatno = configuration['dodatno']
    epsg = configuration['epsg']
    edge_wgs84 = configuration['edge_wgs84']
    slikal = configuration['slikal']
    slikad = configuration['slikad']
    dtk50_folder = configuration['dtk50_folder']
    output_file = configuration['output_file']

    map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, map_to_grid = get_grid_and_map((map_size_w_m, map_size_h_m), (map_w, map_s, map_e, map_n), dtk50_folder)
    
    border_bottom = draw_grid(map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, epsg, edge_wgs84, map_to_grid)

    markings_bbox = (
        GRID_MARGIN_M[3],
        float(border_bottom),
        map_size_w_m - GRID_MARGIN_M[1],
        map_size_h_m - 0.005
    )

    draw_markings(map_img, markings_bbox, naslov1, naslov2, dodatno, slikal, slikad, epsg, edge_wgs84, target_scale, real_to_map_tr)

    map_img.save(output_file, dpi=(TARGET_DPI, TARGET_DPI))

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python create_map.py <base64_configuration>')
        exit(1)
    configuration = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
    create_map(configuration)
    exit(0)

raise NotImplementedError('This script is meant to be run as a standalone script.')
