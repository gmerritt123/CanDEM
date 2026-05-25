# -*- coding: utf-8 -*-
"""
Created on Wed Mar 27 12:29:12 2024

@author: Gaelen
"""

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


class CanDEM:
    '''
    class for retrieving HR DEM from 
    '''
    
    def __init__(self,domain_file, base_url= r"https://datacube.services.geo.ca/stac/api/search"):
        dmn = geopd.read_file(domain_file)
        assert dmn.crs == 'epsg:4326', 'domain file must be lat long EPSG (4326)'
        assert len(dmn) == 1,'domain file must be only a single polygon'
        self.domain_file = domain_file
        self.domain_gdf = dmn
        geojson_dict = mapping(dmn['geometry'].iloc[0])
        geojson_string = json.dumps(geojson_dict) #gets polygon payload
        self.geojson = geojson_string       
        self.payload = {
            "collections": ["hrdem-mosaic-1m", "hrdem-mosaic-2m"],
            "intersects": geojson_string,
            "limit": 5
        }
        self.asset_dict = self.getAssets(base_url,self.payload)
        
    def getAssets(self,url,payload):
        response = requests.get(url, params=payload)
        response.raise_for_status() # Ensure the request succeeded
        # Parse the STAC GeoJSON feature collection result
        stac_data = response.json()    
        asset_dict = {}
        for feature in stac_data.get("features", []):
            print(f"Feature ID: {feature['id']}")
            if '2m' in feature['id']:
                k = '2m'            
            elif '1m' in feature['id']:
                k = '1m'
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






