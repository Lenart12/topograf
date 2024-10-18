# Topograf

# [https://topograf.scuke.si](https://topograf.scuke.si)


### Web interface
![Predogled](/res/preview.png)


### Created maps

![Karta](/res/created_preview.png)


## Project Overview

Topograf is a project designed to create and topographic maps. It utilizes various geospatial libraries and tools to generate maps with detailed grid and marking configurations. The project is structured to handle raster data, generate map previews, and create final map outputs in PDF format.


## Key Components

### `create_map/create_map.py`

This script is the core of the map creation process. It includes functions to handle raster data, draw grids, and add markings to the maps. Key functions include:

- `create_map(configuration)`: Main function to create a map based on the provided configuration.
- `get_preview_image(bounds, epsg, raster_folder)`: Generates a preview image of the map.
- `draw_grid(...)`: Draws the grid on the map.
- `draw_markings(...)`: Adds markings and annotations to the map.

### `src` Sveltekit page frontend

Webpage frontend created with the SvelteKit framework. Its routes include
* `/` Main page index, where maps are created
* `/maps/[map_id]` Created map output
* `/api/create_map` Api for creating a map
* `/api/map_preview` Api for creating map preview (on which controll points will be added)

### Configuration

The project uses a configuration file to manage settings and paths. The `.env.template` file provides a template for the required environment variables.


## Dependencies

The `create_map` python script project relies on several Python libraries, including:

* PIL (Pillow) for image processing.
* pyproj for coordinate transformations.
* rasterio for handling raster data.
* shapely for geometric operations.

Frontend dependencies are managed with `npm` and are installed with `npm i` command.
