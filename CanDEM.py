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

import fiona
from zipfile import ZipFile
fiona.drvsupport.supported_drivers['kml'] = 'rw'
fiona.drvsupport.supported_drivers['KML'] = 'rw'
fiona.drvsupport.supported_drivers['LIBKML'] = 'rw'

class CanDEM:
    '''
    class for retrieving DEM tile footprints and their corresponding high res (1M download resolution) ftp link
    '''
    
    def __init__(self,footprint_dir):
        assert os.path.exists(footprint_dir+r'\\'+'footprints_meta.csv'), 'footprints_meta.csv needs to be in footprint dir!'
        self.footprint_dir = footprint_dir
    
    def downloadFootprints(self):
        '''downloads all the kmz files for every footprint region'''
        fp = pd.read_csv(self.footprint_dir+'\\footprints_meta.csv')
        fpf = fp['Download link for datasets footprints in KMZ format for the first coordinate system'].to_list()
        for f in fpf:
            download(f,self.footprint_dir)
    
    def consolidateFootprints(self,output_filename=None):
        '''extracts each kmz file and consolidates into a single geodataframe of every tile footprint'''
        gdf = geopd.GeoDataFrame()
        for f in glob.glob(self.footprint_dir+r'\\*.kmz'):
            print(f)
            kmz = ZipFile(f,'r')
            kmz.extract('doc.kml',self.footprint_dir+r'\\Temp')
            app = geopd.read_file(self.footprint_dir+r'\\Temp\doc.kml')[['Name','description','geometry']]
            #getting download links out of the description field using html parsing magic
            dl_links = []
            for i,r in app.iterrows():
                desc = r['description']
                soup = BeautifulSoup(desc,'html.parser')
                hrefs = [x['href'] for x in soup.find_all('a',href=True)] #grabs all hrefs
                opts = [x.split(r'/') for x in hrefs] #breaks up directory structure
                #fragile but fits current ftp dir
                #gets the index corresponding to the dtm download
                dtm_ind = [i for i,x in enumerate(opts) if x[7][0:3]=='dtm' and x[-1][0:3]=='dtm'][0] 
                dl_links.append(hrefs[dtm_ind])
            app['dl'] = dl_links
            # [['Name','geometry']]
            gdf = pd.concat([gdf,app])
        self.footprint_gdf = gdf.reset_index(drop=True)
        if output_filename is not None:
            gdf.to_file(self.footprint_dir+'\\'+output_filename)
           
    def setFootprintGdf(self,gdf):
        '''bypasses downloadFootprints and consolidateFootprints by pointing the instance to a loaded gdf of the consolidate footprints'''
        self.footprint_gdf = gdf

                
def download(url,directory,filename=None):
    # make an HTTP request within a context manager
    with requests.get(url, stream=True) as r:        
        # check header to get content length, in bytes
        total_length = int(r.headers.get("Content-Length"))
        if filename==None:
            local_filename = url.split('/')[-1]
        else: 
            local_filename = filename
        # implement progress bar via tqdm
        with tqdm.wrapattr(r.raw, "read", total=total_length, desc="")as raw:
            # save the output to a file
            with open(directory+r'\\'+local_filename, 'wb')as output:
                shutil.copyfileobj(raw, output)
                
def getDLSize(url):
    '''given a download url, gets the size of what the download should be'''
    with requests.get(url, stream=True) as r:
        total_length = int(r.headers.get("Content-Length"))
    return total_length/10**6     



