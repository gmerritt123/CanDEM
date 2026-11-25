# -*- coding: utf-8 -*-
"""
Created on Wed Mar 27 12:29:12 2024

@author: Gaelen
"""
from __future__ import annotations
from bs4 import BeautifulSoup
import requests
from tqdm import tqdm
import shutil
import pandas as pd
import sys
import os
from osgeo import gdal, osr
import geopandas as geopd
from shapely.geometry import Polygon
import glob
from urllib.parse import urljoin
# import fiona
from zipfile import ZipFile
import json
from shapely.geometry import Polygon, mapping
import numpy as np
import math
import os
import sys


import json
import math
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shapely
from requests.adapters import HTTPAdapter
from shapely.geometry import MultiPolygon, Polygon
from urllib3.util.retry import Retry

gdal.UseExceptions()

class CanDEM:
    '''
    class for retrieving HR DEM from 
    '''
    
    def __init__(self,domain_file, base_url= r"https://datacube.services.geo.ca/stac/api/search"):
        if isinstance(domain_file,str):
            dmn = geopd.read_file(domain_file)
        else:
            assert isinstance(domain_file,geopd.GeoDataFrame),'domain_file must be geodataframe or path to one'
            dmn = domain_file
        assert dmn.crs == 'epsg:4326', 'domain file must be lat long EPSG (4326)'
        assert len(dmn) == 1,'domain file must be only a single polygon'
        self.domain_file = domain_file
        self.domain_gdf = dmn
        geojson_dict = mapping(dmn['geometry'].iloc[0])
        self.geojson = geojson_dict
        self.payload = {
            "collections": ["hrdem-mosaic-1m", "hrdem-mosaic-2m"],
            # "intersects": geojson_string,
            "intersects":geojson_dict,
            "limit": 5
        }
        self.asset_dict = self.getAssets(base_url,self.payload)
        
    def getAssets(self,url,payload):
        response = requests.post(url, json=self.payload)
        response.raise_for_status() # Ensure the request succeeded
        # Parse the STAC GeoJSON feature collection result
        stac_data = response.json()    
        asset_dict = {'1m':[],'2m':[]}
        for feature in stac_data.get("features", []):
            print(f"Feature ID: {feature['id']}")
            if '2m' in feature['id']:
                k = '2m'            
            elif '1m' in feature['id']:
                k = '1m'
            else:
                continue
            asset_dict[k] = []
            # Extract the download URLs for the DTM (Digital Terrain Model) or DSM
            assets = feature.get("assets", {})
            # print(assets)
            if "dtm" in assets:
                # print(f"  DTM URL: {assets['dtm']['href']}")
                asset_dict[k].append(assets['dtm']['href'])
        return asset_dict
    
    def estimate_download_size(self, url):
        """Calculates the expected output dimensions and maximum uncompressed file size."""
        # 1. Instantly read remote metadata headers (takes milliseconds)
        ds = gdal.Open('/vsicurl/'+url)
        wkt = ds.GetProjection()
        #create a reprojected clipping polygon
        polygon = self.domain_gdf.to_crs(wkt)['geometry'].iloc[0]
        geotransform = ds.GetGeoTransform()
        pixel_width = abs(geotransform[1])   # Typically 1.0 for this HRDEM
        pixel_height = abs(geotransform[5])  # Typically 1.0 for this HRDEM
        # Get Data Type (Float32 = 4 Bytes, Int16 = 2 Bytes, etc.)
        band = ds.GetRasterBand(1)
        bytes_per_pixel = gdal.GetDataTypeSize(band.DataType)//8
        
        # 2. Get the rectangular outer bounding box of your Shapely polygon
        minx, miny, maxx, maxy = polygon.bounds
        # 3. Convert geographic distance (meters) to target pixels
        out_width = math.ceil((maxx - minx) / pixel_width)
        out_height = math.ceil((maxy - miny) / pixel_height)
        
        # 4. Apply the size calculation formula
        total_bytes = out_width * out_height * bytes_per_pixel * ds.RasterCount
        size_mb = total_bytes / (1024 * 1024)    
        print("--- Pre-Download Assessment ---")
        print(f"Output Raster Dimensions : {out_width} x {out_height} pixels")
        print(f"Estimated Max File Size  : {size_mb:.2f} MB")
        print("--------------------------------")
        # Clean up dataset connection pointer
        ds = None
        
    def DL_DEM(self,url,output_file,dstSRS=None):
        #get the epsg of the raster
        ds = gdal.Open('/vsicurl/'+url)
        wkt = ds.GetProjection()
        #create a reprojected clipping polygon
        dmn_poly = self.domain_gdf.to_crs(wkt)['geometry'].iloc[0]
        geojson_dict = mapping(dmn_poly)
        geojson_structure = {
                            "type": "FeatureCollection",
                            "features": [{
                                "type": "Feature",
                                "geometry": geojson_dict,
                                "properties": {}
                            }]
                        }
        geojson_feature = json.dumps(geojson_structure)
        # print(geojson_feature)
        # 4. Write the GeoJSON string into GDAL's in-memory virtual file system
        # This creates a "fake" file path that GDAL utilities can read directly
        vsimem_geojson_path = "/vsimem/clip_poly.geojson"
        gdal.FileFromMemBuffer(vsimem_geojson_path,geojson_feature)
        if dstSRS == None:
            dstSRS = wkt
        # 5. Configure the Warp options to match your exact command-line flags
        warp_options = gdal.WarpOptions(
            cutlineDSName=vsimem_geojson_path,  # -cutline
            cropToCutline=True,                 # -crop_to_cutline
            dstNodata=-9999,
            cutlineSRS = wkt,
            dstSRS=dstSRS                     
            )
        # estimate_download_size(dmn_poly,'/vsicurl/'+url)
        try:
            print("Streaming remote raster and applying polygon mask...")
            # 6. Execute the Warp operation
            out_ds = gdal.Warp(output_file, '/vsicurl/'+url, options=warp_options,callback=gdal.TermProgress_nocb)
            out_ds = None
            print(f"✅ Successfully created: {output_file}")
        
        finally:
            # 7. Clean up the in-memory virtual file to free up RAM
            gdal.Unlink(vsimem_geojson_path)

# """
# Extract elevation data from Mapzen/AWS "Terrarium" Global Terrain Tiles using GDAL only
# (no rasterio / pyproj / PIL).

    # https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png

# Terrarium encoding (256x256 RGB PNG, Web Mercator tile grid):
    # elevation_m = (R * 256 + G + B / 256) - 32768

# Requires: numpy, pandas, shapely>=2, requests, GDAL (osgeo)

# e.g. usage:

# tt = CDM.TerrainTiles(dmn['geometry'].iloc[0]) #polygon geometry in 4326
# tt.options gives various resolutions
# tt.download(dst_crs='epsg:26912',record=tt.options.loc[15],out_path=r'F:\Projects\SWAT\SWAT_Chauvin_11-26\GIS\DEM.tif')

# """
class TerrainTiles:
    URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
    TILE_SIZE = 256
    ORIGIN = 20037508.342789244          # half-width of Web Mercator extent (m)
    R = 6378137.0
    MAX_LAT = 85.0511287798066           # Web Mercator latitude limit
    MAX_ZOOM = 15                        # highest zoom published for terrarium

    def __init__(
        self,
        polygon: Polygon | MultiPolygon,
        min_zoom: int = 0,
        max_zoom: int = 15,
        avg_tile_kb: float = 80.0,
        max_exact_tiles: int = 50_000,
    ):
        """
        Parameters
        ----------
        polygon : shapely Polygon/MultiPolygon in EPSG:4326 (lon/lat).
        min_zoom, max_zoom : range of zoom levels to tabulate (0-15).
        avg_tile_kb : assumed average PNG size per tile, used only for the
            download-size estimate (real tiles range ~10 KB to >150 KB).
        max_exact_tiles : above this bbox tile count the polygon/tile
            intersection test is skipped and the bbox count is used
            (flagged by `n_tiles_exact=False`).
        """
        if not isinstance(polygon, (Polygon, MultiPolygon)) or polygon.is_empty:
            raise TypeError("polygon must be a non-empty shapely Polygon or MultiPolygon")
        if not polygon.is_valid:
            polygon = shapely.make_valid(polygon)
        if not (0 <= min_zoom <= max_zoom <= self.MAX_ZOOM):
            raise ValueError(f"need 0 <= min_zoom <= max_zoom <= {self.MAX_ZOOM}")

        clipped = shapely.clip_by_rect(polygon, -180, -self.MAX_LAT, 180, self.MAX_LAT)
        if clipped.is_empty:
            raise ValueError("polygon lies entirely outside the Web Mercator tile extent")

        self.polygon = clipped
        self.min_zoom, self.max_zoom = min_zoom, max_zoom
        self.avg_tile_kb = avg_tile_kb
        self.max_exact_tiles = max_exact_tiles

        # Polygon bounds in EPSG:3857 (lon/lat -> mercator is monotonic, so bounds map directly)
        minx, miny, maxx, maxy = self.polygon.bounds
        self._bounds_3857 = (
            self._lon_to_x(minx), self._lat_to_y(miny),
            self._lon_to_x(maxx), self._lat_to_y(maxy),
        )

        self.options: pd.DataFrame = self._build_options()

    # ------------------------------------------------------------------ #
    # Tile / mercator math
    # ------------------------------------------------------------------ #
    @classmethod
    def _lon_to_x(cls, lon: float) -> float:
        return lon * cls.ORIGIN / 180.0

    @classmethod
    def _lat_to_y(cls, lat: float) -> float:
        return cls.R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    @staticmethod
    def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
        n = 2 ** z
        x = int(math.floor((lon + 180.0) / 360.0 * n))
        y = int(math.floor((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n))
        return min(max(x, 0), n - 1), min(max(y, 0), n - 1)

    def _tile_range(self, z: int) -> tuple[int, int, int, int]:
        minx, miny, maxx, maxy = self.polygon.bounds
        x0, y1 = self._lonlat_to_tile(minx, miny, z)   # south-west -> max y
        x1, y0 = self._lonlat_to_tile(maxx, maxy, z)   # north-east -> min y
        return x0, x1, y0, y1

    @staticmethod
    def _tile_bounds_lonlat(x, y, z):
        """Vectorised (west, south, east, north) of tiles, in degrees."""
        n = 2.0 ** z
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        west = x / n * 360.0 - 180.0
        east = (x + 1) / n * 360.0 - 180.0
        north = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y / n))))
        south = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + 1) / n))))
        return west, south, east, north

    def _intersecting_tiles(self, z, x0, x1, y0, y1) -> np.ndarray:
        """(N, 2) array of (x, y) for tiles that intersect the polygon."""
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        xs, ys = xs.ravel(), ys.ravel()
        w, s, e, n = self._tile_bounds_lonlat(xs, ys, z)
        shapely.prepare(self.polygon)
        keep = shapely.intersects(self.polygon, shapely.box(w, s, e, n))
        return np.column_stack([xs[keep], ys[keep]])

    # ------------------------------------------------------------------ #
    # Options table
    # ------------------------------------------------------------------ #
    def _build_options(self) -> pd.DataFrame:
        lat_c = self.polygon.centroid.y
        minx, miny, maxx, maxy = self._bounds_3857
        rows = []
        for z in range(self.min_zoom, self.max_zoom + 1):
            x0, x1, y0, y1 = self._tile_range(z)
            n_bbox = (x1 - x0 + 1) * (y1 - y0 + 1)
            if n_bbox <= self.max_exact_tiles:
                n_tiles, exact = len(self._intersecting_tiles(z, x0, x1, y0, y1)), True
            else:
                n_tiles, exact = n_bbox, False

            px_m = 2 * self.ORIGIN / (self.TILE_SIZE * 2 ** z)      # mercator m/pixel
            width = max(1, math.ceil((maxx - minx) / px_m))
            height = max(1, math.ceil((maxy - miny) / px_m))
            rows.append(dict(
                zoom=z,
                resolution_m=px_m * math.cos(math.radians(lat_c)),  # ~ground resolution
                pixel_size_3857_m=px_m,
                x_min=x0, x_max=x1, y_min=y0, y_max=y1,
                n_tiles_bbox=n_bbox,
                n_tiles=n_tiles,
                n_tiles_exact=exact,
                est_download_mb=n_tiles * self.avg_tile_kb / 1024.0,
                est_width_px=width,
                est_height_px=height,
                est_tif_mb=width * height * 4 / 1e6,                # float32, uncompressed
            ))
        return pd.DataFrame(rows).set_index("zoom", drop=False).rename_axis(None)

    # ------------------------------------------------------------------ #
    # Download / extract
    # ------------------------------------------------------------------ #
    @staticmethod
    def _make_session(pool_size: int) -> requests.Session:
        s = requests.Session()
        retry = Retry(total=4, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry, pool_connections=pool_size, pool_maxsize=pool_size)
        s.mount("https://", adapter)
        return s

    def _fetch_tile(self, session, z, x, y, timeout) -> np.ndarray | None:
        """Download one tile, decode PNG with GDAL (/vsimem), return float32 metres. None if 404."""
        r = session.get(self.URL.format(z=z, x=x, y=y), timeout=timeout)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        name = f"/vsimem/tile_{uuid.uuid4().hex}.png"
        gdal.FileFromMemBuffer(name, r.content)
        try:
            ds = gdal.Open(name)
            rgb = ds.ReadAsArray().astype(np.float32)   # (bands, rows, cols)
            ds = None
        finally:
            gdal.Unlink(name)
        return rgb[0] * 256.0 + rgb[1] + rgb[2] / 256.0 - 32768.0

    def download(
        self,
        record: pd.Series | pd.DataFrame | dict,
        out_path: str | Path,
        dst_crs,
        resampling: str = "bilinear",
        nodata: float = -9999.0,
        all_touched: bool = True,
        max_tiles: int = 5000,
        max_workers: int = 8,
        timeout: float = 30.0,
    ) -> Path:
        """
        Download tiles for one row of `self.options`, clip to the polygon,
        reproject, and write a GeoTIFF (float32, elevation in metres).

        Parameters
        ----------
        record : a row of `self.options` (e.g. `tt.options.loc[12]`, `tt.options.iloc[[3]]`).
        out_path : output .tif path (parent dirs are created).
        dst_crs : "EPSG:32617", an int EPSG code, WKT, PROJ string, ...
        resampling : any gdalwarp -r name (near, bilinear, cubic, cubicspline, lanczos, ...).
        nodata : nodata value for outside-polygon / missing-tile cells.
        all_touched : include cells touched by the polygon boundary (else centre-in-polygon).
        max_tiles : safety limit on number of tiles fetched.
        """
        if isinstance(record, pd.DataFrame):
            if len(record) != 1:
                raise ValueError("record DataFrame must contain exactly one row")
            record = record.iloc[0]
        z = int(record["zoom"])
        x0, x1 = int(record["x_min"]), int(record["x_max"])
        y0, y1 = int(record["y_min"]), int(record["y_max"])

        tiles = self._intersecting_tiles(z, x0, x1, y0, y1)
        if len(tiles) > max_tiles:
            raise ValueError(
                f"{len(tiles)} tiles required at zoom {z} (> max_tiles={max_tiles}). "
                "Raise max_tiles or pick a lower zoom."
            )

        # ---- fetch + mosaic ---------------------------------------------
        T = self.TILE_SIZE
        nx, ny = x1 - x0 + 1, y1 - y0 + 1
        mosaic = np.full((ny * T, nx * T), nodata, dtype=np.float32)
        session = self._make_session(max_workers)

        def work(xy):
            x, y = int(xy[0]), int(xy[1])
            return x, y, self._fetch_tile(session, z, x, y, timeout)

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for x, y, arr in ex.map(work, tiles):
                if arr is not None:
                    r0, c0 = (y - y0) * T, (x - x0) * T
                    mosaic[r0:r0 + T, c0:c0 + T] = arr

        # ---- crop mosaic to polygon bbox (+2px) to save memory -----------
        px = 2 * self.ORIGIN / (T * 2 ** z)
        left = -self.ORIGIN + x0 * T * px
        top = self.ORIGIN - y0 * T * px
        minx, miny, maxx, maxy = self._bounds_3857
        pad = 2
        c_a = max(int(math.floor((minx - left) / px)) - pad, 0)
        c_b = min(int(math.ceil((maxx - left) / px)) + pad, mosaic.shape[1])
        r_a = max(int(math.floor((top - maxy) / px)) - pad, 0)
        r_b = min(int(math.ceil((top - miny) / px)) + pad, mosaic.shape[0])
        src = np.ascontiguousarray(mosaic[r_a:r_b, c_a:c_b])
        h, w = src.shape

        # ---- in-memory GDAL dataset in EPSG:3857 -------------------------
        src_srs = osr.SpatialReference()
        src_srs.ImportFromEPSG(3857)
        mem = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Float32)
        mem.SetGeoTransform((left + c_a * px, px, 0.0, top - r_a * px, 0.0, -px))
        mem.SetProjection(src_srs.ExportToWkt())
        band = mem.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        band.WriteArray(src)
        band.FlushCache()

        # ---- polygon cutline (GeoJSON in /vsimem; GeoJSON is lon/lat 4326) -
        cut = f"/vsimem/cutline_{uuid.uuid4().hex}.geojson"
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": json.loads(shapely.to_geojson(self.polygon))}
        ]}
        gdal.FileFromMemBuffer(cut, json.dumps(fc).encode())

        # ---- resolve destination CRS -------------------------------------
        dst_srs = osr.SpatialReference()
        if isinstance(dst_crs, int):
            dst_srs.ImportFromEPSG(dst_crs)
        else:
            dst_srs.SetFromUserInput(str(dst_crs))
        dst_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

        # ---- warp + clip + write in one step -----------------------------
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            opts = gdal.WarpOptions(
                format="GTiff",
                dstSRS=dst_srs.ExportToWkt(),
                srcNodata=nodata, dstNodata=nodata,
                outputType=gdal.GDT_Float32,
                resampleAlg=resampling,
                cutlineDSName=cut,
                cropToCutline=True,
                warpOptions=["CUTLINE_ALL_TOUCHED=TRUE"] if all_touched else None,
                creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"],
                multithread=True,
            )
            out = gdal.Warp(str(out_path), mem, options=opts)
            out.SetMetadata({"SOURCE": "Mapzen/AWS Terrain Tiles (terrarium)",
                             "ZOOM": str(z), "UNITS": "metres"})
            out.GetRasterBand(1).SetDescription("elevation (m)")
            out.FlushCache()
            out = None
        finally:
            gdal.Unlink(cut)
            mem = None
        return out_path





