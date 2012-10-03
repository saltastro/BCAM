#!/usr/bin/env python

import re
import pyfits
import numpy as np

import logging

from pylibapogee import pylibapogee as apg
from ctypes import *

libfli = CDLL("/home/tim/BCAM/libfli-1.104/libfli.so")

def add_coloring_to_emit_ansi(fn):
    def new(*args):
        levelno = args[1].levelno
        if(levelno >= 50):
            color = '\x1b[31m'  # red
        elif(levelno >= 40):
            color = '\x1b[31m'  # red
        elif(levelno >= 30):
            color = '\x1b[33m'  # yellow
        elif(levelno >= 20):
            color = '\x1b[32m'  # green
        elif(levelno >= 10):
            color = '\x1b[35m'  # pink
        else:
            color = '\x1b[0m'  # normal
        args[1].levelname = color + args[1].levelname + '\x1b[0m'  # normal
        return fn(*args)
    return new

# Initialize logger
logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
b_log = logging.getLogger()
fh = logging.FileHandler("bcam.log")
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter("%(asctime)s: %(levelname)s - %(message)s"))
b_log.addHandler(fh)
ch = logging.StreamHandler()
f = logging.Formatter("%(levelname)s: %(message)s")
ch.setFormatter(f)
logging.StreamHandler.emit = add_coloring_to_emit_ansi(logging.StreamHandler.emit)


class Focuser:
    """
    class for talking to an FLI precision focuser.  requires FLI's fliusb-1.3 and libfli-1.104.
    """
    attached = False

    def __init__(self, device="/dev/fliusb0"):
        if not Focuser.attached:
            Focuser.handle = c_long()
            err = libfli.FLIOpen(byref(Focuser.handle), device, 0x02 | 0x300)
            if err != 0:
                b_log.warn("Can't open FLI device!")
                Focuser.handle = None
                Focuser.attached = False
            else:
                b_log.info("Opened FLI focuser at %s with handle %d." % 
                           (device, Focuser.handle.value))
                Focuser.attached = True

    def position(self):
        if Focuser.attached:
            position = c_long()
            err = libfli.FLIGetStepperPosition(Focuser.handle, byref(position))
            if err != 0:
                b_log.warn("Can't query stepper position: error in read.")
                return None
            else:
                b_log.info("FLI Focuser position: %d", position.value)
                return position.value
        else:
            b_log.warn("Can't query stepper position: no device attached.")

    def upper_limit(self):
        if Focuser.attached:
            limit = c_long()
            err = libfli.FLIGetFocuserExtent(Focuser.handle, byref(limit))
            if err != 0:
                b_log.warn("Can't query stepper limit: error in read.")
                return None
            else:
                b_log.info("FLI Focuser maximum position: %d", limit.value)
                return limit.value
        else:
            b_log.warn("Can't query stepper limit: no device attached.")

    def lower_limit(self):
        if Focuser.attached:
            b_log.info("FLI Focuser minimum position: %d", 0)
            return 0
        else:
            b_log.warn("Can't query stepper limit: no device attached.")
            return None

    def temperature(self):
        if Focuser.attached:
            t = c_double()
            err = libfli.FLIReadTemperature(Focuser.handle, 0, byref(t))
            if err != 0:
                b_log.warn("Can't query focuser temperature: error in read.")
                return None
            else:
                b_log.info("FLI Focuser internal temperature (C): %.2f" % t.value)
                return t.value
        else:
            b_log.warn("Can't query focuser temperature: no device attached.")
            return None

    def home(self):
        if Focuser.attached:
            b_log.info("Homing FLI Focuser....")
            err = libfli.FLIHomeFocuser(Focuser.handle)
            if err != 0:
                b_log.warn("Can't home focuser: error in command.")
                return False
            else:
                b_log.info("FLI Focuser successfully homed.")
                return True
        else:
            b_log.warn("Can't home focuser: no device attached.")
            return False

    def step(self, steps, async=False):
        if Focuser.attached:
            now = self.position()
            new = now + steps
            if new > self.upper_limit() or new < self.lower_limit():
                b_log.warn("Attempted motion to position %d is out of range (%d,%d)." 
                           % (new,self.upper_limit(),self.lower_limit()))
                return False

            if not async:
                b_log.info("Stepping FLI Focuser %d steps from %d...." % 
                           (steps, now))
                err = libfli.FLIStepMotor(Focuser.handle, c_long(steps))
            else:
                b_log.info("Stepping FLI Focuser asynchronously %d steps from %d...." % 
                           (steps, self.position()))
                err = libfli.FLIStepMotorAsync(Focuser.handle, c_long(steps))

            if err != 0:
                b_log.warn("Can't step focuser: error in command.")
                return False
            else:
                b_log.info("FLI Focuser successfully commanded to step to position %d." % 
                           new)
                return True
        else:
            b_log.warn("Can't step focuser: no device attached.")
            return False

    def goto(self, position, async=False):
        now = self.position()
        delta = position - now
        self.step(delta, async=async)

class BCAM:
    """
    class for talking to BCAM which consists of an Apogee Alta U16M CCD and an FLI precision
    focuser.  requires libapogee to be installed and uses the SWIG python bindings to that from 
    http://sourceforge.net/projects/apogee-driver/
    """
    camera = None
    foc = Focuser()

    def __init__(self):
        # find and initialize camera
        if not BCAM.camera:
            cameras = self.getUsbApogees()
            if cameras[0]:
                try:
                    BCAM.camera = self.createAndConnectCam(cameras[0])
                except:
                    BCAM.camera = None
            else:
                BCAM.camera = None

    def getUsbApogees(self):
        msg = apg.FindDeviceUsb().Find()
        return self.parseDeviceStr(msg)

    def parseDeviceStr(self, deviceStr):
        #MUST include the < in the grouping, so the regex
        #search functions below will find the last item in the
        #string
        deviceStrList = re.findall("<d>(.*?<)/d>", deviceStr)
        deviceDictList = []
        
        for device in deviceStrList:
            # 1 here, because the match above will
            # always pick up the < making the device
            # string len == 1
            if(1 >= len(device)):
            #nothing to parse move to the next 
            #item in the list
                continue
        
            devDict = {}
            mm = re.search("interface=(.*?)[,|<]", device)
            devDict["interface"] = mm.group(1)
            
            mmA = re.search("address=(.*?)[,|<]", device)
        
            if "ethernet" == devDict["interface"]:
                mmP = re.search("port=(.*?)[,|<]", device)
                devDict["address"] = mmA.group(1) + ":" + mmP.group(1)
            else:
                devDict["address"] = mmA.group(1)
                
            mm = re.search("id=(.*?)[,|<]", device)
            devDict["id"] = mm.group(1)  
            
            mm = re.search("firmwareRev=(.*?)[,|<]", device)
            devDict["firmwareRev"] = mm.group(1)
            
            mm = re.search("model=(.*?)[,|<]", device)
            devDict["model"] = mm.group(1) 
            
            mm = re.search("interfaceStatus=(.*?)[,|<]", device)
            status = mm.group(1).replace("\"","")
            devDict["interfaceStatus"] = status  
            
            if(len(devDict) != 6):
                #this device didn't contain the correct data
                #go to the next device
                continue
                    
            devDict["camType"] = devDict["model"].split("-")[0]
            deviceDictList.append(devDict)
        
        return deviceDictList
    
    def createAndConnectCam(self, devDict):
        cam = None
        if("AltaU" == devDict["camType"] or
           "AltaE" == devDict["camType"]):
            cam = apg.Alta()
    
        if( "Ascent" == devDict["camType"] ):
            cam = apg.Ascent()
    
        cam.OpenConnection(devDict["interface"],
                           devDict["address"],
                           int(devDict["firmwareRev"],16),
                           int(devDict["id"],16))
    
        cam.Init()
    
        b_log.info( "Camera %s connected and initialized via %s" %
                       ( cam.GetModel(), devDict["interface"] ) )
        return cam

    def acquireImage(self, exp, shutter, xbin=1, ybin=1, startx=0, starty=0, endx=4096, endy=4096):
        cam = BCAM.camera

#        status = None
#        while status != apg.Status_Idle:
#            status = cam.GetImagingStatus()

        if startx > endx:
            startx, endx = endx, startx
        if starty > endy:
            starty, endy = endy, starty

        if ybin > cam.GetMaxBinRows():
            ybin = cam.GetMaxBinRows()
        if endy > cam.GetMaxImgRows():
            endy = cam.GetMaxImgRows()
        if xbin > cam.GetMaxBinCols():
            xbin = cam.GetMaxBinCols()
        if endx > cam.GetMaxImgCols():
            endx = cam.GetMaxImgCols()

        cam.SetRoiStartRow(starty)
        rows = int( (endy-starty)/ybin )
        cam.SetRoiNumRows(rows)
        cam.SetRoiBinRow(ybin)
						
        cam.SetRoiStartCol(startx)
        cols = int( (endx-startx)/xbin )
        cam.SetRoiNumCols(cols)
        cam.SetRoiBinCol(xbin)
	
        status = None
        cam.StartExposure(exp, shutter)
        while status != apg.Status_ImageReady:
            status = cam.GetImagingStatus()

        if shutter:
            imtype = "Light"
        else:
            imtype = "Dark"
        msg = "Reading %s \t exp=%f, xbin=%d, ybin=%d, r=%d, c=%d" % \
            (imtype, exp, xbin, ybin, rows, cols)
        b_log.info(msg)

        data = cam.GetImage()

        return np.array(data, dtype=np.uint16).reshape(rows,cols)

    def makeHeader(self, ccdtype, exptime):
        cam = BCAM.camera
        f = BCAM.foc
        cards = []
        cards.append(pyfits.createCard("CCDTYPE", ccdtype, "CCD type"))
        cards.append(pyfits.createCard("EXPTIME", exptime, "Exposure time (s)"))
        cards.append(pyfits.createCard("PXHEIGHT", cam.GetPixelHeight(), "Pixel height in um"))
        cards.append(pyfits.createCard("PXWIDTH", cam.GetPixelWidth(), "Pixel width in um"))
        cards.append(pyfits.createCard("CCDMAX_X", cam.GetMaxImgCols(), "CCD width in pixels"))
        cards.append(pyfits.createCard("CCDMAX_Y", cam.GetMaxImgRows(), "CCD height in pixels"))
        binx = cam.GetRoiBinCol()
        biny = cam.GetRoiBinRow()
        cards.append(pyfits.createCard("ROIBIN_X", binx, "X binning"))
        cards.append(pyfits.createCard("ROIBIN_Y", biny, "Y binning"))
        startx = cam.GetRoiStartCol()
        starty = cam.GetRoiStartRow()
        nx = cam.GetRoiNumCols()
        ny = cam.GetRoiNumRows()
        endx = startx + binx*nx
        endy = starty + biny*ny
        cards.append(pyfits.createCard("ROIMIN_X", startx, "ROI start X"))
        cards.append(pyfits.createCard("ROIMAX_X", endx, "ROI end X"))
        cards.append(pyfits.createCard("ROIMIN_Y", starty, "ROI start Y"))
        cards.append(pyfits.createCard("ROIMAX_Y", endy, "ROI end Y"))
        cards.append(pyfits.createCard("ROI_NX", nx, "ROI width"))
        cards.append(pyfits.createCard("ROI_NY", ny, "ROI height"))
        cards.append(pyfits.createCard("SETPOINT", 
                                       float("%.2f" % cam.GetCoolerSetPoint()), 
                                       "Cooler setpoint in C"))
        cards.append(pyfits.createCard("COOLING", cam.GetCoolerStatus(), "Cooler status"))
        cards.append(pyfits.createCard("COOLDRIV", 
                                       float("%.2f" % cam.GetCoolerDrive()), 
                                       "Cooler drive (%)"))
        cards.append(pyfits.createCard("FANMODE", cam.GetFanMode(), "Cooler fan mode"))
        cards.append(pyfits.createCard("BACKOFF", 
                                       float("%.2f" % cam.GetCoolerBackoffPoint()), 
                                       "Cooler backoff point"))
        cards.append(pyfits.createCard("T_CCD", 
                                       float("%.2f" % cam.GetTempCcd()), 
                                       "CCD temperature in C"))
        cards.append(pyfits.createCard("T_HSINK", 
                                       float("%.2f" % cam.GetTempHeatsink()), 
                                       "Camera heatsink temperature in C"))
        cards.append(pyfits.createCard("MODEL", cam.GetModel(), "Camera model"))
        cards.append(pyfits.createCard("SENSOR", cam.GetSensor(), "Camera sensor"))
        if f.attached:
            cards.append(pyfits.createCard("BCAMFOC", f.position(), "BCAM focus position"))
            cards.append(pyfits.createCard("FLITEMP", 
                                           f.temperature(), 
                                           "BCAM focuser temperature (C)"))
        return pyfits.Header(cards=cards)

#############
if __name__ == "__main__":
    bcam = BCAM()
    ccd = bcam.camera
    t_ccd = ccd.GetTempCcd()
    t_heatsink = ccd.GetTempHeatsink()

    print "T(CCD) = %.2f; T(Heatsink) = %.2f" % (t_ccd, t_heatsink)

    exptime = 0.05

    blah = bcam.acquireImage(0.0, False, xbin=8, ybin=8)
    dark = bcam.acquireImage(exptime, False, xbin=8, ybin=8).astype(np.int32)
    light = bcam.acquireImage(exptime, False, xbin=8, ybin=8).astype(np.int32)

    print dark.mean()
    print light.mean()

    header = bcam.makeHeader("OBJECT", exptime)
    pyfits.writeto("test.fits", light-dark, header=header, clobber=True)