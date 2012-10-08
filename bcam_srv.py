#!/usr/bin/env python

import cStringIO
import pyfits
import bcam
import web
from web import form

render = web.template.render('templates/')

urls = (
    '/', 'index',
    '/status', 'index',
    '/expose', 'expose',
    '/cooling', 'cooling',
    '/focus', 'focus',
)

b = bcam.BCAM()
ccd = b.camera
foc = b.foc

class index:
    def GET(self):
        return render.index(ccd, foc)

class expose:
    form = web.form.Form(
        web.form.Textbox('exptime', 
                         web.form.notnull, 
                         web.form.regexp('\d+', 'Must be a digit'),
                         web.form.Validator('Must be >= 0.0', lambda x:float(x)>=0.0),
                         value="2.0",
                         size=30,
                         description="Exposure Time (s):",
                         ),
        web.form.Textbox('xbin', 
                         web.form.notnull, 
                         web.form.regexp('\d+', 'Must be a digit'),
                         web.form.Validator('Must be > 0', lambda x:int(x)>0),
                         value="8",
                         size=30,
                         description="X binning:",
                         ),
        web.form.Textbox('ybin', 
                         web.form.notnull, 
                         web.form.regexp('\d+', 'Must be a digit'),
                         web.form.Validator('Must be > 0', lambda x:int(x)>0),
                         value="8",
                         size=30,
                         description="Y binning:",
                         ),
        web.form.Checkbox('shutter', 
                          value='Open', 
                          checked=True, 
                          description="Open shutter:"),
    )

    def GET(self):
        return render.expform(expose.form)

    def POST(self):
        f = expose.form() 
        if not f.validates(): 
            return render.expform(f)
        else:
            exptime = float(f.d.exptime)
            xbin = int(f.d.xbin)
            ybin = int(f.d.ybin)
            shutter = f.d.shutter
            image = b.acquireImage(exptime, shutter, xbin=xbin, ybin=ybin)
            if shutter:
                header = b.makeHeader('OBJECT', exptime)
            elif exptime > 0.0:
                header = b.makeHeader('DARK', exptime)
            else:
                header = b.makeHeader('BIAS', exptime)

            fitsData = cStringIO.StringIO()
            pyfits.writeto(fitsData, image, header=header, clobber=True)
            fitsData.seek(0)
            web.header("Content-Type", 'image/fits')
            web.header("Content-Disposition", "attachment; filename=bcam.fits")
            return fitsData.read()

class cooling:
    form = web.form.Form(
        web.form.Dropdown('fanmode',
                          args=[('0', 'Off'), ('1', 'Low'), ('2', 'Medium'), ('3', 'High')],
                          value="%d" % ccd.GetFanMode(),
                          description="Fan Mode"),
        web.form.Textbox('backoff', 
                         web.form.notnull, 
                         web.form.Validator('Must be >= 1.0', lambda x:float(x)>=1.0),
                         value="%.2f" % ccd.GetCoolerBackoffPoint(),
                         size=30,
                         description="Cooler Backoff Temp (C):",
                         ),
        web.form.Textbox('setpoint', 
                         web.form.notnull, 
                         web.form.Validator('Must be >= -40.0', lambda x:float(x)>=-40.0),
                         value="%.2f" % ccd.GetCoolerSetPoint(),
                         size=30,
                         description="Cooler Set-Point (C):",
                         ),
        web.form.Button('Configure Cooling',
                         type='submit',
                        ),
        )

    def GET(self):
        return render.cooling(cooling.form)

    def POST(self):
        f = cooling.form()
        if not f.validates():
            return render.cooling(f)
        else:
            fanmode = int(f.d.fanmode)
            backoff = float(f.d.backoff)
            setpoint = float(f.d.setpoint)
            ccd.SetCooler(True)
            ccd.SetFanMode(fanmode)
            ccd.SetCoolerBackoffPoint(backoff)
            ccd.SetCoolerSetPoint(setpoint)
            return render.cooling(f)

class focus:
    form = web.form.Form(
        web.form.Textbox('focus', 
                         web.form.notnull, 
                         web.form.Validator('Must be >= 0.0 and <= 7000', 
                                            lambda x:int(x)>=0 and int(x)<=7000),
                         value="%d" % foc.position(),
                         size=30,
                         description="BCAM Focus Position:",
                         ),
        web.form.Button('Set Focus',
                         type='submit',
                        ),
    )

    def GET(self):
        return render.focus(focus.form)

    def POST(self):
        f = focus.form()
        if not f.validates():
            return render.focus(f)
        else:
            newfocus = int(f.d.focus)
            foc.goto(newfocus, async=True)
            return "<html><meta http-equiv=\"refresh\" content='0;URL=\"/status\"></html>"

if __name__ == "__main__":

    app = web.application(urls, globals())
    app.run()
