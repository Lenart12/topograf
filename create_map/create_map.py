from PIL import Image, ImageDraw, ImageFont
import sys
import math
import json
import pyproj
import json
import itertools
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
    
    return map_img, grid_img, add_colrow_to_transformer(map_to_world_tr), add_colrow_to_transformer(grid_to_world_tr), add_colrow_to_transformer(real_to_map_tr)


def draw_grid(map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, epsg, edge_wgs84):
    map_draw = ImageDraw.Draw(map_img)
    
    # Draw grid on the map
    map_img.paste(grid_img, real_to_map_tr.colrow(GRID_MARGIN_M[3], GRID_MARGIN_M[0]))

    # Draw grid border
    border0 = map_to_world_tr.colrow(*grid_to_world_tr.xy(-1, -1))
    map_draw.rectangle((border0[0], border0[1], border0[0] + grid_img.size[0] + 1, border0[1] + grid_img.size[1] + 1), outline='black', width=2)

    grid_font = ImageFont.truetype('timesi.ttf', 28)

    # Draw coordinate system
    if epsg != 'Brez':
        cs_from = pyproj.CRS.from_epsg(3794)
        cs_to = pyproj.CRS.from_epsg(int(epsg.split(':')[1]))
        cs_tr = pyproj.Transformer.from_crs(cs_from, cs_to)

        """
        # Do not draw grid lines near black pixels in the map
        def should_draw_grid_line(x0, y0, line_dir):
            if x0 < 0 or x0 >= a4_size_px[0] or y0 < 0 or y0 >= a4_size_px[1]:
                return False
            
            # check 3 wide area += 10 dir around the point for dark pixels (black or near black)
            if line_dir == 'x':
                for x in range(x0 - 2, x0 + 3):
                    for y in range(y0 - 10, y0 + 10):
                        col = a4_img_src.getpixel((x, y))
                        if col[0] < 20 and col[1] < 20 and col[2] < 20:
                            return False
            else:
                for x in range(x0 - 10, x0 + 10):
                    for y in range(y0 - 2, y0 + 3):
                        col = a4_img_src.getpixel((x, y))
                        if col[0] < 20 and col[1] < 20 and col[2] < 20:
                            return False

            return True

        # Draw grid lines on the map
        def draw_grid_line(x0, y0, x1, y1, line_dir):
            x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
            if line_dir == 'x':
                assert(x0 == x1)
                for y in range(int(y0), int(y1)):
                    if not should_draw_grid_line(x0, y, line_dir):
                        a4_draw.line((x0, y, x0 + GRID_THICKNESS - 1, y), fill=GRID_COLOR)
                    else:
                        # Darken the pixel
                        col = a4_img.getpixel((x0, y))
                        col = (max(0, col[0] - 90), max(0, col[1] - 90), max(0, col[2] - 90))              
                        a4_draw.line((x0, y, x0 + GRID_THICKNESS - 1, y), fill=col)

            elif line_dir == 'y':
                assert(y0 == y1)
                for x in range(int(x0), int(x1)):
                    if not HIDE_GRID_NEAR_BLACK_PIXELS or should_draw_grid_line(x, y0, line_dir):
                        a4_draw.line((x, y0, x, y0 + GRID_THICKNESS - 1), fill=GRID_COLOR)
                    else:
                        # Darken the pixel
                        col = a4_img.getpixel((x, y0))
                        col = (max(0, col[0] - 90), max(0, col[1] - 90), max(0, col[2] - 90))
                        a4_draw.line((x, y0, x, y0 + GRID_THICKNESS - 1), fill=col)

        superscript_map = {
            "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}

        # Draw the grid and grid coordinate labels on map borders
        for x in range(int(a4_grid0[0]), int(a4_grid1[0] + GRID_SIZE_M), GRID_SIZE_M):
            p0 = image_to_a4_image(*utm_to_image(x, a4_im0[1]))
            p1 = image_to_a4_image(*utm_to_image(x, a4_im1[1]))
            draw_grid_line(p0[0], p0[1] + 1, p1[0], p1[1] - 1, 'x')
            cord = f'{int(x):06}'
            txt = f'{superscript_map[cord[-6]]}{cord[-5:-3]}'
            a4_draw.text((p0[0], p0[1] - 5), txt, fill='black', align='center', anchor='ms', font=GRID_FONT)
            a4_draw.text((p1[0], p1[1] + 5), txt, fill='black', align='center', anchor='mt', font=GRID_FONT)

        for y in range(int(a4_grid1[1]), int(a4_grid0[1] + GRID_SIZE_M), GRID_SIZE_M):
            p0 = image_to_a4_image(*utm_to_image(a4_im0[0], y))
            p1 = image_to_a4_image(*utm_to_image(a4_im1[0], y))
            draw_grid_line(p0[0] + 1, p0[1], p1[0] - 1, p1[1], 'y')
            cord = f'{int(y):06}'
            txt = f'{superscript_map[cord[-6]]}{cord[-5:-3]}'
            a4_draw.text((p0[0] - 5, p0[1]), txt, fill='black', align='center', anchor='rm', font=GRID_FONT)
            a4_draw.text((p1[0] + 5, p1[1]), txt, fill='black', align='center', anchor='lm', font=GRID_FONT)
        """
        
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

    map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr = get_grid_and_map((map_size_w_m, map_size_h_m), (map_w, map_s, map_e, map_n), dtk50_folder)
    
    draw_grid(map_img, grid_img, map_to_world_tr, grid_to_world_tr, real_to_map_tr, epsg, edge_wgs84)

    map_img.save(output_file, dpi=(TARGET_DPI, TARGET_DPI))

if __name__ == '__main__':
    configuration = {}
    if len(sys.argv) != 2:
        configuration = {
            'map_size_w_m': 0.297,
            'map_size_h_m': 0.21,
            'map_w': 447136,
            'map_s': 70883,
            'map_e': 453851,
            'map_n': 75370,
            'target_scale': 25000,
            'naslov1': 'Karta za orientacijo',
            'naslov2': '',
            'dodatno': 'Izdelal RJŠ za potrebe orientacije. Karta ni bila reambulirana.',
            'epsg': 'EPSG:3794',
            'edge_wgs84': True,
            'slikal': '',
            'slikad': '',
            'dtk50_folder': 'C:\\Users\\Lenart\\Desktop\\DTK50\\res',
            'output_file': 'test.png'
        }
    else:
        configuration = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))

    create_map(configuration)
    exit(0)

raise NotImplementedError('This script is meant to be run as a standalone script.')
DEGREE_GRID_MARGIN = [30, 45, 30, 45] # Margin around the map for degree markers in pixels
GRID_THICKNESS = 2
FONT_TITLE = ImageFont.truetype('times.ttf', 36)
GRID_FONT = ImageFont.truetype('timesi.ttf', 28)
SCALE_FONT = ImageFont.truetype('timesi.ttf', 16)
HIDE_GRID_NEAR_BLACK_PIXELS = True
GRID_COLOR = '#151515'


# Degree grid transformer
CRS_D96_TM = pyproj.CRS.from_epsg(3794 ) # D96/TM
CRS_WGS84 = pyproj.CRS.from_epsg(4326)  # WGS84
utm_to_deg = pyproj.Transformer.from_crs(CRS_D96_TM, CRS_WGS84)
deg_to_utm = pyproj.Transformer.from_crs(CRS_WGS84, CRS_D96_TM)


# Function for converting between image and UTM coordinates
# x, y - image coordinates
# E, N - UTM coordinates
def image_to_utm(x, y):
    return (calibration_points[0][2] + (x - calibration_points[0][0]) * scale_x, calibration_points[0][3] + (y - calibration_points[0][1]) * scale_y)

# Function for converting UTM coordinates to image coordinates
# E, N - UTM coordinates
# x, y - image coordinates
def utm_to_image(E, N):
    return ((E - calibration_points[0][2]) / scale_x + calibration_points[0][0], (N - calibration_points[0][3]) / scale_y + calibration_points[0][1])

map_img_src = map_img.copy()
draw = ImageDraw.Draw(map_img)



#### WORLD TO MAP #####
            
# Draw the A4 paper
# A4 paper size in meters
a4_size_world = (TARGET_MAP_SIZE_M[0] * TARGET_MAP_SCALE, TARGET_MAP_SIZE_M[1] * TARGET_MAP_SCALE)
a4_0 = utm_to_image(*MAP_ORIGIN)
a4_1 = utm_to_image(MAP_ORIGIN[0] + a4_size_world[0], MAP_ORIGIN[1] - a4_size_world[1])


# Calculate the grid coordinates of the A4 paper
a4_im0 = image_to_utm(a4_0[0] + GRID_MARGIN[3], a4_0[1] + GRID_MARGIN[0])
a4_im1 = image_to_utm(a4_1[0] - GRID_MARGIN[1], a4_1[1] - GRID_MARGIN[2])

a4_grid0 = (math.ceil(a4_im0[0] / GRID_SIZE_M) * GRID_SIZE_M, math.floor(a4_im0[1] / GRID_SIZE_M) * GRID_SIZE_M)
a4_grid1 = (math.floor(a4_im1[0] / GRID_SIZE_M) * GRID_SIZE_M, math.ceil(a4_im1[1] / GRID_SIZE_M) * GRID_SIZE_M)

# Draw the grid coordinates of the A4 paper
if DRAW_DEBUG_GRID:
    a4_im0_image = utm_to_image(*a4_im0)
    draw.ellipse((a4_im0_image[0]-5, a4_im0_image[1]-5, a4_im0_image[0]+5, a4_im0_image[1]+5), fill='blue')
    draw.text((a4_im0_image[0]+10, a4_im0_image[1]-10), f'({a4_im0[0]//1000%100}, {a4_im0[1]//1000%100})', fill='blue')
    a4_im1_image = utm_to_image(*a4_im1)
    draw.ellipse((a4_im1_image[0]-5, a4_im1_image[1]-5, a4_im1_image[0]+5, a4_im1_image[1]+5), fill='blue')
    draw.text((a4_im1_image[0]+10, a4_im1_image[1]-10), f'({a4_im1[0]//1000%100}, {a4_im1[1]//1000%100})', fill='blue')

    a4_grid0_image = utm_to_image(*a4_grid0)
    draw.ellipse((a4_grid0_image[0]-5, a4_grid0_image[1]-5, a4_grid0_image[0]+5, a4_grid0_image[1]+5), fill='blue')
    draw.text((a4_grid0_image[0]+10, a4_grid0_image[1]-10), f'({a4_grid0[0]//1000%100}, {a4_grid0[1]//1000%100})', fill='blue')
    a4_grid1_image = utm_to_image(*a4_grid1)
    draw.ellipse((a4_grid1_image[0]-5, a4_grid1_image[1]-5, a4_grid1_image[0]+5, a4_grid1_image[1]+5), fill='blue')
    draw.text((a4_grid1_image[0]+10, a4_grid1_image[1]-10), f'({a4_grid1[0]//1000%100}, {a4_grid1[1]//1000%100})', fill='blue')


def image_to_a4_image(x, y):
    return (x - a4_0[0], y - a4_0[1])
def a4_image_to_image(x, y):
    return (x + a4_0[0], y + a4_0[1])

# Calulate DPI
# A4 paper size in pixels
a4_size_px = (a4_1[0] - a4_0[0] - 1, a4_1[1] - a4_0[1] - 1)
# DPI
dpm = (a4_size_px[0] / TARGET_MAP_SIZE_M[0], a4_size_px[1] / TARGET_MAP_SIZE_M[1])
# Convert dpm to dpi
dpi_xy = (dpm[0] * 0.0254, dpm[1] * 0.0254)
dpi = sum(dpi_xy) / 2
# print(f'DPI: {dpi}, DPI_X: {dpi_xy[0]}, DPI_Y: {dpi_xy[1]}, Relative error: {abs(dpi_xy[0] - dpi_xy[1]) / dpi * 100}%')

# Create a new image with the A4 paper
a4_img = Image.new('RGB', [int(p) for p in a4_size_px], 0xFFFFFF)
a4_draw = ImageDraw.Draw(a4_img)

# Draw the map inside the margin
selected_area = map_img_src.crop((a4_0[0] + GRID_MARGIN[3], a4_0[1] + GRID_MARGIN[0], a4_1[0] - GRID_MARGIN[1] - 1, a4_1[1] - GRID_MARGIN[2]))
def change_contrast(img, level):
    if level == 0:
        return img
    factor = (259 * (level + 255)) / (255 * (259 - level))
    def contrast(c):
        return 128 + factor * (c - 128)
    return img.point(contrast)

selected_area = change_contrast(selected_area, 0)

if e('DRAW_MAP_BACKGROUND', bool):
    a4_img.paste(selected_area, (GRID_MARGIN[3], GRID_MARGIN[0]))

#### -WORLD TO MAP- #####


#### MAP STYLING #####

# Create copy for grid line generation
a4_img_src = a4_img.copy()

# Draw border of the map
a4_draw.rectangle((GRID_MARGIN[3], GRID_MARGIN[0], a4_size_px[0] - GRID_MARGIN[1], a4_size_px[1] - GRID_MARGIN[2]), outline='black', width=GRID_THICKNESS)

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
    a4_img.paste(text_img, (int(xy[0] + xof * text_img.width), int(xy[1] + yof * text_img.height)), text_img)

# Draw the degree markers
a4_draw.rectangle(
    (GRID_MARGIN[3] - DEGREE_GRID_MARGIN[3], GRID_MARGIN[0] - DEGREE_GRID_MARGIN[0],
     a4_size_px[0] - GRID_MARGIN[1] + DEGREE_GRID_MARGIN[1], a4_size_px[1] - GRID_MARGIN[2] + DEGREE_GRID_MARGIN[2]),
     outline='black', width=GRID_THICKNESS)
# NW
a4_draw.line((GRID_MARGIN[3] - DEGREE_GRID_MARGIN[3], GRID_MARGIN[0],
              GRID_MARGIN[3], GRID_MARGIN[0]), fill='black', width=GRID_THICKNESS)
a4_draw.line((GRID_MARGIN[3], GRID_MARGIN[0] - DEGREE_GRID_MARGIN[0],
                GRID_MARGIN[3], GRID_MARGIN[0]), fill='black', width=GRID_THICKNESS)
gkNW = a4_im0
utm_to_deg_NW = utm_to_deg.transform(*gkNW)
a4_draw_text_rotate((GRID_MARGIN[3] - DEGREE_GRID_MARGIN[3] - 3, GRID_MARGIN[0]), -1, 0, f'φ = {deg_to_deg_min_sec(utm_to_deg_NW[0])}', 90, GRID_FONT)
a4_draw.text((GRID_MARGIN[3], GRID_MARGIN[0] - DEGREE_GRID_MARGIN[0] - 3), f'λ = {deg_to_deg_min_sec(utm_to_deg_NW[1])}', fill='black', align='center', anchor='lb', font=GRID_FONT)

# NE
a4_draw.line((a4_size_px[0] - GRID_MARGIN[1] + DEGREE_GRID_MARGIN[1], GRID_MARGIN[0] + 1,
              a4_size_px[0] - GRID_MARGIN[1], GRID_MARGIN[0] + 1), fill='black', width=GRID_THICKNESS)
a4_draw.line((a4_size_px[0] - GRID_MARGIN[1] - 1, GRID_MARGIN[0] - DEGREE_GRID_MARGIN[0],
                a4_size_px[0] - GRID_MARGIN[1] - 1, GRID_MARGIN[0]), fill='black', width=GRID_THICKNESS)
gkNE = (a4_im1[0], a4_im0[1])
utm_to_deg_NE = utm_to_deg.transform(*gkNE)
a4_draw_text_rotate((a4_size_px[0] - GRID_MARGIN[1] + DEGREE_GRID_MARGIN[1] + 3, GRID_MARGIN[0]), 0, 0, f'φ = {deg_to_deg_min_sec(utm_to_deg_NE[0])}', -90, GRID_FONT)
a4_draw.text((a4_size_px[0] - GRID_MARGIN[1], GRID_MARGIN[0] - DEGREE_GRID_MARGIN[0] - 3), f'λ = {deg_to_deg_min_sec(utm_to_deg_NE[1])}', fill='black', align='center', anchor='rb', font=GRID_FONT)

# SE
a4_draw.line((a4_size_px[0] - GRID_MARGIN[1] + DEGREE_GRID_MARGIN[1], a4_size_px[1] - GRID_MARGIN[2],
              a4_size_px[0] - GRID_MARGIN[1], a4_size_px[1] - GRID_MARGIN[2]), fill='black', width=GRID_THICKNESS)
a4_draw.line((a4_size_px[0] - GRID_MARGIN[1], a4_size_px[1] - GRID_MARGIN[2] + DEGREE_GRID_MARGIN[2],
                a4_size_px[0] - GRID_MARGIN[1], a4_size_px[1] - GRID_MARGIN[2]), fill='black', width=GRID_THICKNESS)
gkSE = a4_im1
utm_to_deg_SE = utm_to_deg.transform(*gkSE)
a4_draw_text_rotate((a4_size_px[0] - GRID_MARGIN[1] + DEGREE_GRID_MARGIN[1] + 3, a4_size_px[1] - GRID_MARGIN[2]), 0, -1, f'φ = {deg_to_deg_min_sec(utm_to_deg_SE[0])}', -90, GRID_FONT)
a4_draw.text((a4_size_px[0] - GRID_MARGIN[1], a4_size_px[1] - GRID_MARGIN[2] + DEGREE_GRID_MARGIN[2] + 3), f'λ = {deg_to_deg_min_sec(utm_to_deg_SE[1])}', fill='black', align='center', anchor='rt', font=GRID_FONT)

# SW
a4_draw.line((GRID_MARGIN[3] - DEGREE_GRID_MARGIN[3], a4_size_px[1] - GRID_MARGIN[2] - 1,
              GRID_MARGIN[3], a4_size_px[1] - GRID_MARGIN[2] - 1), fill='black', width=GRID_THICKNESS)
a4_draw.line((GRID_MARGIN[3] + 1, a4_size_px[1] - GRID_MARGIN[2] + DEGREE_GRID_MARGIN[2],
                GRID_MARGIN[3] + 1, a4_size_px[1] - GRID_MARGIN[2]), fill='black', width=GRID_THICKNESS)
gkSW = (a4_im0[0], a4_im1[1])
utm_to_deg_SW = utm_to_deg.transform(*gkSW)
a4_draw_text_rotate((GRID_MARGIN[3] - DEGREE_GRID_MARGIN[3] - 3, a4_size_px[1] - GRID_MARGIN[2]), -1, -1, f'φ = {deg_to_deg_min_sec(utm_to_deg_SW[0])}', 90, GRID_FONT)
a4_draw.text((GRID_MARGIN[3], a4_size_px[1] - GRID_MARGIN[2] + DEGREE_GRID_MARGIN[2] + 3), f'λ = {deg_to_deg_min_sec(utm_to_deg_SW[1])}', fill='black', align='center', anchor='lt', font=GRID_FONT)

# Draw minute's markers
# NW - NE
sec_nw_ne = (math.ceil(utm_to_deg_NW[1] * 60), math.floor(utm_to_deg_NE[1] * 60))
nw_ne_lat = (utm_to_deg_NW[0] + utm_to_deg_NE[0]) / 2
for sec in range(sec_nw_ne[0], sec_nw_ne[1] + 1):
    xy = image_to_a4_image(*utm_to_image(*deg_to_utm.transform(nw_ne_lat, sec / 60)))
    a4_draw.line((xy[0], GRID_MARGIN[0] - DEGREE_GRID_MARGIN[0], xy[0], GRID_MARGIN[0] - DEGREE_GRID_MARGIN[0] + 15), fill='black', width=GRID_THICKNESS)

# NE - SE
sec_ne_se = (math.floor(utm_to_deg_SE[0] * 60), math.ceil(utm_to_deg_NE[0] * 60))
ne_se_lon = (utm_to_deg_NE[1] + utm_to_deg_SE[1]) / 2
for sec in range(sec_ne_se[0], sec_ne_se[1] + 1):
    xy = image_to_a4_image(*utm_to_image(*deg_to_utm.transform(sec / 60, ne_se_lon)))
    a4_draw.line((a4_size_px[0] - GRID_MARGIN[1] + DEGREE_GRID_MARGIN[1], xy[1],  a4_size_px[0] - GRID_MARGIN[1] + DEGREE_GRID_MARGIN[1] - 15, xy[1]), fill='black', width=GRID_THICKNESS)

# SE - SW
sec_se_sw = (math.floor(utm_to_deg_SW[1] * 60), math.ceil(utm_to_deg_SE[1] * 60))
se_sw_lat = (utm_to_deg_SW[0] + utm_to_deg_SE[0]) / 2
for sec in range(sec_se_sw[0], sec_se_sw[1] + 1):
    xy = image_to_a4_image(*utm_to_image(*deg_to_utm.transform(se_sw_lat, sec / 60)))
    a4_draw.line((xy[0], a4_size_px[1] - GRID_MARGIN[2] + DEGREE_GRID_MARGIN[2], xy[0], a4_size_px[1] - GRID_MARGIN[2] + DEGREE_GRID_MARGIN[2] - 15), fill='black', width=GRID_THICKNESS)

# SW - NW
sec_sw_nw = (math.ceil(utm_to_deg_SW[0] * 60), math.floor(utm_to_deg_NW[0] * 60))
sw_nw_lon = (utm_to_deg_SW[1] + utm_to_deg_NW[1]) / 2
for sec in range(sec_sw_nw[0], sec_sw_nw[1] + 1):
    xy = image_to_a4_image(*utm_to_image(*deg_to_utm.transform(sec / 60, sw_nw_lon)))
    a4_draw.line((GRID_MARGIN[3] - DEGREE_GRID_MARGIN[3], xy[1], GRID_MARGIN[3] - DEGREE_GRID_MARGIN[3] + 15, xy[1]), fill='black', width=GRID_THICKNESS)

# Supersampling draw
SS_RATIO = CP_SUPERSAMPLING
ss_img = Image.new('RGBA', [int(p * SS_RATIO) for p in a4_size_px])
cp_draw = ImageDraw.Draw(ss_img)
# Draw control points
ellipse_size = CONTROL_POINT_SIZE * TARGET_MAP_SCALE / scale_x / 2 * SS_RATIO
first_cp = None
last_cp = None

def triangle_distance(theta):
    return ellipse_size / (2 * math.cos(math.acos(math.sin(3*(theta + math.pi)))/3))

for i in itertools.count():
    cp = e(f'KT_{i}', str)
    if not cp:
        break
    cp = cp.split(',')
    cp = [float(cp[0]), float(cp[1])]
    cp_utm = deg_to_utm.transform(*cp)
    cp_img = utm_to_image(*cp_utm)
    cp_a4_img = image_to_a4_image(*cp_img)
    ss_a4_img = [c * SS_RATIO for c in cp_a4_img]


    # Middle dot
    if CONTROL_POINT_DOT_SIZE:
        cp_draw.ellipse(
            (ss_a4_img[0] - CONTROL_POINT_DOT_SIZE * SS_RATIO, ss_a4_img[1] - CONTROL_POINT_DOT_SIZE * SS_RATIO,
             ss_a4_img[0] + CONTROL_POINT_DOT_SIZE * SS_RATIO, ss_a4_img[1] + CONTROL_POINT_DOT_SIZE * SS_RATIO), fill=CONTROL_POINT_COLOR)

    cp_text = f'KT{i}'
    # Draw triangle for first control point
    if i == 0:
        cp_draw.polygon([
            (ss_a4_img[0], ss_a4_img[1] - ellipse_size),
            (ss_a4_img[0] + ellipse_size * math.cos(math.radians(30)), ss_a4_img[1] + ellipse_size * math.sin(math.radians(30))),
            (ss_a4_img[0] - ellipse_size * math.cos(math.radians(30)), ss_a4_img[1] + ellipse_size * math.sin(math.radians(30))),
        ], outline=CONTROL_POINT_COLOR, width=3 * SS_RATIO)
        first_cp = ss_a4_img
        cp_text = 'START'
    else:
        # Circle outline
        cp_draw.ellipse((ss_a4_img[0] - ellipse_size, ss_a4_img[1] - ellipse_size, ss_a4_img[0] + ellipse_size, ss_a4_img[1] + ellipse_size), outline=CONTROL_POINT_COLOR, width=3 * SS_RATIO)
        # Line to previous control point but only between the elipse borders
        theta = math.atan2(ss_a4_img[1] - last_cp[1], ss_a4_img[0] - last_cp[0])
        last_cp_radius = ellipse_size
        if i == 1: # First is triangle
            last_cp_radius = triangle_distance(theta)

        if DRAW_CP_TRACK:
            cp_draw.line(
                (last_cp[0] + last_cp_radius * math.cos(theta), last_cp[1] + last_cp_radius * math.sin(theta),
                ss_a4_img[0] - ellipse_size * math.cos(theta), ss_a4_img[1] - ellipse_size * math.sin(theta)), fill=CONTROL_POINT_COLOR, width=3 * SS_RATIO)

    last_cp = ss_a4_img
    # Draw CP number
    a4_draw.text((cp_a4_img[0] + ellipse_size / SS_RATIO + 3, cp_a4_img[1]), cp_text, fill=CONTROL_POINT_COLOR, align='center', anchor='lb', font=FONT_TITLE)

# Draw line between first and last control point
if first_cp and last_cp and DRAW_CP_TRACK:
    theta = math.atan2(last_cp[1] - first_cp[1], last_cp[0] - first_cp[0])
    last_cp_radius = triangle_distance(theta)
    cp_draw.line(
        (first_cp[0] + last_cp_radius * math.cos(theta), first_cp[1] + last_cp_radius * math.sin(theta),
         last_cp[0] - ellipse_size * math.cos(theta), last_cp[1] - ellipse_size * math.sin(theta)), fill=CONTROL_POINT_COLOR, width=3 * SS_RATIO)

# Reduce supersampled image to normal size
sampled_img = ss_img.resize(a4_img.size)
a4_img.paste(sampled_img, (0, 0), sampled_img)

# Draw scale
scale_y_offset = 33
scale_x_offset = lambda x: GRID_MARGIN[3] + x/scale_x
a4_draw.line((scale_x_offset(0), a4_size_px[1] - scale_y_offset, scale_x_offset(1000), a4_size_px[1] - scale_y_offset), fill='black', width=GRID_THICKNESS)
draw_vertical_line = lambda x, h: a4_draw.line((scale_x_offset(x), a4_size_px[1] - scale_y_offset, scale_x_offset(x), a4_size_px[1] - scale_y_offset - h), fill='black')
draw_vertical_line(0, 15)
draw_vertical_line(500, 15)
for x in range(0, 500, 25):
    draw_vertical_line(x, 10 if x % 100 != 0 else 13)
draw_vertical_line(750, 10)
draw_vertical_line(1000, 15)
a4_draw.text((scale_x_offset(0), a4_size_px[1] - scale_y_offset - 20), '500m', fill='black', align='center', anchor='ls', font=SCALE_FONT)
a4_draw.text((scale_x_offset(500), a4_size_px[1] - scale_y_offset - 20), '0m', fill='black', align='center', anchor='ms', font=SCALE_FONT)
a4_draw.text((scale_x_offset(1000), a4_size_px[1] - scale_y_offset - 20), '500m', fill='black', align='center', anchor='rs', font=SCALE_FONT)
a4_draw.text((scale_x_offset(1000) + 10, a4_size_px[1] - scale_y_offset - 53), MAP_INFO, fill='black', align='left', font=SCALE_FONT)

# Draw logos
LOGO_SIZE = 80

if e('MAP_LOGO_LEFT', str):
    logo_left = Image.open(e('MAP_LOGO_LEFT', str))
    logo_left.thumbnail((LOGO_SIZE, LOGO_SIZE))
    a4_img.paste(logo_left, (int(a4_size_px[0] * 3/8 - LOGO_SIZE/2), int(a4_size_px[1] - 111)), logo_left)

if e('MAP_LOGO_RIGHT', str):
    logo_right = Image.open(e('MAP_LOGO_RIGHT', str))
    logo_right.thumbnail((LOGO_SIZE, LOGO_SIZE))
    a4_img.paste(logo_right, (int(a4_size_px[0] * 5/8 - LOGO_SIZE/2), int(a4_size_px[1] - 111)), logo_right)


# Draw 3mm inset border around the A4 paper
if e('DRAW_PRINT_BORDER', bool):
    border_px_x = 0.0045 * dpm[0]
    border_px_y = 0.004 * dpm[1]
    a4_draw.rectangle((border_px_x, border_px_y, a4_size_px[0] - border_px_x, a4_size_px[1] - border_px_y), outline='red', width=1)
#### -MAP STYLING- #####

# Draw title
a4_draw.text((a4_size_px[0] / 2, a4_size_px[1] - 73), MAP_TITLE, fill='black', align='center', anchor='mm', font=FONT_TITLE)

# Draw credit
a4_draw.text((a4_size_px[0] - GRID_MARGIN[1], a4_size_px[1] - 73), MAP_CREDIT, fill='black', align='right', anchor='rs', font=SCALE_FONT)

# Save the debug image

# Make sure the output directory exists
os.makedirs(os.path.dirname(e('MAP_OUTPUT_PREFIX', str)), exist_ok=True)

output_prefix = e('MAP_OUTPUT_PREFIX', str)
if e('OUTPUT_CALIBRATED_MAP', bool):
    map_img.save(f'{output_prefix}-calibrated.png', dpi=dpi_xy)

