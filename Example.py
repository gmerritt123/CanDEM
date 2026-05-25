# -*- coding: utf-8 -*-
"""
Created on Wed Mar 27 20:04:30 2024

@author: Gaelen
"""
import sys
from osgeo import gdal
import geopandas as geopd
import glob
import os
sys.path.append(r'C:\Repo\CanDEM')
import CanDEM

#example
cdm = CanDEM.CanDEM(domain_file=r'C:\Repo\CanDEM\AOI.geojson') #area of interest in lat long (epsg:4326)

#all dem assets touching will populate in cdm.asset_dict --> this one has only one 2m
print(cdm.asset_dict)

#this will estimate the download size by querying a dem asset with your domain (and handling projection stuff)
cdm.estimate_download_size(cdm.asset_dict['2m'][0])

#downloads it
cdm.DL_DEM(url=cdm.asset_dict['2m'][0]
            ,output_file=r'C:\Repo\CanDEM\DEM.tif'
            ,dstSRS='epsg:26912')
#%%
# putting all the rasters together workflow if you need to download multiple

# fs = glob.glob(r'where your tifs are\*.tif') #all the tifs downloaded

# ofile = r'output place\Mosaic.tif'
       
# #%% build a virtual raster (you can load this .vrt into Q, it's just a text file containing instructions to load all the rasters concurrently)
# vrt_options = gdal.BuildVRTOptions(resampleAlg='nearest')
# vrt = gdal.BuildVRT(r'output place\VRT.vrt',fs,options=vrt_options)
# del vrt
# #%% convert that vrt into one big raster, completing the mosaic
# tr = gdal.Translate(ofile,r'output place\VRT.vrt')
# del tr