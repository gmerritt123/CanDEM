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

import whitebox
wbt = whitebox.WhiteboxTools()
wbt.set_whitebox_dir(r'C:\ProgramData\Anaconda3\envs\geo_env38v1\Lib\site-packages\whitebox')

cdm = CanDEM.CanDEM(footprint_dir=r'C:\Repo\CanDEM\Footprints')

#first time, need to download footprints and consolidate them
cdm.downloadFootprints() #downloads kmz files of all canadian dem tile footprints to footprint dir
cdm.consolidateFootprints(output_filename='Footprints.shp') #aggregates these into one gdf, output_filename = shape file export

#alternatively if you already have these previous two steps done, can skip by just loading in Footprints.shp and setting it as the Footprint Gdf
# gdf = geopd.read_file('C:\Repo\CanDEM\Footprints\Footprints.shp') 
# cdm.setFootprintGdf(gdf)

#%%
#read in your model domain/study area
dmn_f = r'C:\Projects\Barrie_TCE\FEFLOW\import+export\Dmn.shp'
dmn = geopd.read_file(dmn_f)
#go lat long for "universal" projection, and same projection as the footprints
dmn = dmn.to_crs('epsg:4326')
#%%
#simple spatial join to the footprints to get footprints intersecting with model domain
sj = cdm.footprint_gdf.sjoin(dmn,predicate='intersects') 
sj['dl'] #these are the DEMs to download
#%% good idea to check how big a download this would be
sj['Size'] = sj['dl'].apply(lambda x: CanDEM.getDLSize(x)) #gets the size of each download 
sj['Size'].sum() #MB size of all tiles once downloaded
#%%
dl_dir = r'E:\Projects\BarrieTCE\DEM' #where to do the download
#download each of the tiles
for i,r in sj.iterrows():
    print(r['dl'])
    CanDEM.download(r['dl'],dl_dir)    

#%% mosaic them together using whitebox
#WARNING, the skip i'm stepping here is asserting every tile is in the same projection 
# --> need to assert that for locations that might be near UTM Zone boundaries
fs = glob.glob(r'E:\Projects\BarrieTCE\DEM\*.tif')
ofile = r'E:\Projects\BarrieTCE\DEM\Mosaic.tif'
       
wbt.mosaic(
    inputs=fs,  
    output=ofile, 
    method="cc", 
)
#%%