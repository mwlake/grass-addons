#!/usr/bin/env python
"""
@module  library for g.gui.cswbrowser
@brief   GUI csw browser


(C) 2015 by the GRASS Development Team
This program is free software under the GNU General Public License
(>=v2). Read the file COPYING that comes with GRASS for details.

@author Matej Krejci <matejkrejci gmail.com> (GSoC 2015)
"""
import sys,os
try:
    from owslib.csw import CatalogueServiceWeb
except:
    sys.exit('owslib python library is missing. Check requirements on the manual page < https://grasswiki.osgeo.org/wiki/ISO/INSPIRE_Metadata_Support >')

from cswutil import *

from mdutil import yesNo, StaticContext
import tempfile
import json

import webbrowser
import wx
from wx import SplitterWindow
import wx.html as html
from wx.lib.buttons import ThemedGenBitmapTextButton as BitmapBtnTxt
from wx.lib.mixins.listctrl import ListCtrlAutoWidthMixin
import webbrowser
from threading import Thread
import xml.etree.ElementTree as ET
from wx.html import HTML_URL_IMAGE, HTML_OPEN, EVT_HTML_LINK_CLICKED, HW_DEFAULT_STYLE, HW_SCROLLBAR_NEVER, \
    HW_SCROLLBAR_AUTO

# import wx.html2 not supported in 2.8.12.1 (need for CSS support)
from owslib.csw import CatalogueServiceWeb
from owslib.fes import BBox, PropertyIsLike
from owslib.ows import ExceptionReport

import grass.script as grass
from core.utils import GetFormats
from gui_core.forms import GUI
from core.gcmd import RunCommand, GError, GMessage, GWarning
from modules.import_export import GdalImportDialog, GdalOutputDialog, ImportDialog
from subprocess import PIPE
from grass.pygrass.modules import Module
from grass.script import parse_key_val


class ConstraintsBulder(wx.Panel):
    def __init__(self, parent, settings=''):
        wx.Panel.__init__(self, parent=parent, id=wx.ID_ANY)
        self.label = wx.StaticText(self, -1, label="Manual for creating constraints:\n\
*Constraints must be in brackets([]) \n\
*Constraints must be in quotation marks(') \n\
Examples\n\
      OR expression\n\
      a || b || c\n\
      ['a','b','c']\n\
      \n\
      AND expression \n\
       a && b && c\n\
      [['a','b','c']]\n\
      \n\
      More expressions \n\
      (a && b) || c || d || e\n\
      [['a','b'],['c'],['d'],['e']] or [['a','b'],'c','d','e']")

        self.constrCtrl = wx.TextCtrl(self, -1)
        self.applyBtt = wx.Button(self, -1, label='Apply')
        self.cancelBtt = wx.Button(self, -1, label='Cancel')

        self.constrCtrl.SetValue(settings)
        self._layout()

    def _layout(self):
        panelSizer = wx.BoxSizer(wx.VERTICAL)
        panelSizer.Add(self.label)
        panelSizer.AddSpacer(10, 10, 1, wx.EXPAND)
        panelSizer.Add(self.constrCtrl, 1, wx.EXPAND)

        horSizer = wx.BoxSizer(wx.HORIZONTAL)
        horSizer.Add(self.applyBtt)
        horSizer.Add(self.cancelBtt)
        panelSizer.AddSpacer(10, 10, 1, wx.EXPAND)
        panelSizer.Add(horSizer)
        self.SetSizerAndFit(panelSizer)


class CSWBrowserPanel(wx.Panel):
    def __init__(self, parent, main):
        self.context = StaticContext()
        self.config = wx.Config('g.gui.cswbrowser')
        wx.Panel.__init__(self, parent)
        self.parent = main
        self.constraintsWidgets = []
        self.constraintsWidgets1 = []
        self.constraintsAdvanced = False
        self.idResults = []
        self.constString = ''
        sizeConst = 55
        self.splitterBrowser = SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE | wx.SP_BORDER)
        self.context=StaticContext()
        self.connectionFilePath = os.path.join(self.context.lib_path, 'connections_resources.xml')
        self.pnlLeft = wx.Panel(self.splitterBrowser, id=wx.ID_ANY)
        self.pnlRight = wx.Panel(self.splitterBrowser, -1)

        self.keywordLbl = wx.StaticText(self.pnlLeft, -1, 'Keywords')
        self.numResultsLbl = wx.StaticText(self.pnlLeft, -1, 'Max')
        self.catalogLbl = wx.StaticText(self.pnlLeft, -1, 'Catalog')
        self.findResNumLbl = wx.StaticText(self.pnlLeft, -1, '')

        self.advanceChck = wx.CheckBox(self.pnlLeft, label='Advanced')
        self.advanceChck.Bind(wx.EVT_CHECKBOX, self.OnKeywordDialog)
        self.stbFind = wx.StaticBox(self.pnlLeft, -1, 'Filter')
        self.stbSearch = wx.StaticBox(self.pnlLeft, -1, 'Search settings')

        self.catalogCmb = wx.ComboBox(self.pnlLeft, id=-1, pos=wx.DefaultPosition)
        self.keywordCtr = wx.TextCtrl(self.pnlLeft)
        self.catalogCmb.Bind(wx.EVT_COMBOBOX, self.OnSetCatalog)
        w, self.h = self.keywordCtr.GetSize()
        self.numResultsSpin = wx.SpinCtrl(self.pnlLeft, min=1, max=100, initial=20, size=(sizeConst, self.h),
                                          style=wx.ALIGN_RIGHT | wx.SP_ARROW_KEYS)


        self.addKeywordCtr = wx.Button(self.pnlLeft, -1, '+', size=(self.h, self.h))
        self.addKeywordCtr.Bind(wx.EVT_BUTTON, self.addKeyWidget)
        self.findBtt = wx.Button(self.pnlLeft, size=(sizeConst, self.h), label='Search')
        self.findBtt.SetBackgroundColour((255, 127, 80))
        qtyp=['All','Collection','Dataset','Event','Image','InteractiveResource',
            'MovingImage','PhysicalObject','Service','Software','Sound','StillImage','Text']

        self.qtypeCb = wx.ComboBox(self.pnlLeft, id=-1, pos=wx.DefaultPosition,choices=qtyp)
        self.qtypeCb.SetValue("All")
        self.qtypeCb.Disable()
        # -----Results---
        self.resultList = AutoWidthListCtrl(self.pnlLeft)
        self.resultList.Bind(wx.EVT_LIST_ITEM_FOCUSED, self.setTooltip)
        self.resultList.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnRecord)
        self.bttNextItem1 = wx.Button(self.pnlLeft, label=">")
        self.bttNextItem2 = wx.Button(self.pnlLeft, label=">>")
        self.bttBackItem1 = wx.Button(self.pnlLeft, label="<")
        self.bttBackItem2 = wx.Button(self.pnlLeft, label="<<")

        self.bttNextItem1.Bind(wx.EVT_BUTTON, self.OnNavigate, self.bttNextItem1)
        self.bttNextItem2.Bind(wx.EVT_BUTTON, self.OnNavigate, self.bttNextItem2)
        self.bttBackItem1.Bind(wx.EVT_BUTTON, self.OnNavigate, self.bttBackItem1)
        self.bttBackItem2.Bind(wx.EVT_BUTTON, self.OnNavigate, self.bttBackItem2)
        self.findBtt.Bind(wx.EVT_BUTTON, self.OnSearch)
        self.refreshResultList()

        # -----BB---------
        self.stbBB = wx.StaticBox(self.pnlLeft, -1, 'Extent')
        self.bbWestLb = wx.StaticText(self.pnlLeft, -1, 'Xmin')
        self.bbSouthLb = wx.StaticText(self.pnlLeft, -1, 'Ymin')
        self.bbEastLb = wx.StaticText(self.pnlLeft, -1, 'Xmax')
        self.bbNorthLb = wx.StaticText(self.pnlLeft, -1, 'Ymax')

        self.bbWest = wx.TextCtrl(self.pnlLeft)
        self.bbSouth = wx.TextCtrl(self.pnlLeft)
        self.bbEast = wx.TextCtrl(self.pnlLeft)
        self.bbNorth = wx.TextCtrl(self.pnlLeft)
        '''
        self.bbWest.Bind(wx.EVT_TEXT_ENTER, self.OnTypeBB)
        self.bbSouth.Bind(wx.EVT_TEXT_ENTER, self.OnTypeBB)
        self.bbEast.Bind(wx.EVT_TEXT_ENTER, self.OnTypeBB)
        self.bbNorth.Bind(wx.EVT_TEXT_ENTER, self.OnTypeBB)
        '''
        self.bbSetGlobalBtt1 = wx.Button(self.pnlLeft, label="Global")
        self.bbSetMapExtendBtt1 = wx.Button(self.pnlLeft, label="Map extent")
        self.bbSetGlobalBtt1.Bind(wx.EVT_BUTTON, self.setBBoxGlobal)
        self.bbSetMapExtendBtt1.Bind(wx.EVT_BUTTON, self.setBBoxGRASS)
        self.setBBoxGlobal()
        # -----right panel

        self.bttAddWms = wx.Button(self.pnlRight, label="Add WMS")
        self.bttAddWfs = wx.Button(self.pnlRight, label="Add WFS")
        self.bttAddWcs = wx.Button(self.pnlRight, label="Add WCS")
        self.bttAddWms.Bind(wx.EVT_BUTTON, self.OnService, self.bttAddWms)
        self.bttAddWfs.Bind(wx.EVT_BUTTON, self.OnService, self.bttAddWfs)
        self.bttAddWcs.Bind(wx.EVT_BUTTON, self.OnService, self.bttAddWcs)

        self.bttViewRequestXml = wx.Button(self.pnlRight, label="Request XML")
        self.bttViewResponseXml = wx.Button(self.pnlRight, label="Response XML")

        self.bttViewRequestXml.Bind(wx.EVT_BUTTON, self.OnShowReguest)
        self.bttViewResponseXml.Bind(wx.EVT_BUTTON, self.OnShowResponse)

        self.htmlView = html.HtmlWindow(self.pnlRight,
                                        id=-1,
                                        pos=wx.DefaultPosition,
                                        size=wx.DefaultSize,
                                        style=HW_DEFAULT_STYLE | HW_SCROLLBAR_AUTO,
                                        name="metadata")
        self.htmlView.Bind(EVT_HTML_LINK_CLICKED, self.onHtmlLinkClicked)
        #self.htmlView=wx.html2.WebView.New(self.pnlRight, not supported in 2.8.12.1
        self.refreshNavigationButt()
        self._layout()

    '''
    def OnTypeBB(self,evt):
        raw_value = evt.GetValue().strip()
        # numeric check
        print raw_value
        if all(x in '0123456789.+-' for x in raw_value):
            evt.ChangeValue(raw_value)
    '''

    def OnKeywordDialog(self, evt):
        if self.advanceChck.GetValue():
            self.geDialog = wx.Dialog(self, id=wx.ID_ANY,
                                      title='constraints builder',
                                      style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                                      size=wx.DefaultSize,
                                      pos=wx.DefaultPosition)

            self.geDialog.SetSize((500, 500))
            self.constrPnl = ConstraintsBulder(self.geDialog, self.constString)
            self.constrPnl.applyBtt.Bind(wx.EVT_BUTTON, self.OnSetAdvancedConstraints)
            self.constrPnl.cancelBtt.Bind(wx.EVT_BUTTON, self._destroyDialog)
            dbSizer = wx.BoxSizer(wx.VERTICAL)
            dbSizer.Add(self.constrPnl, flag=wx.EXPAND)
            self.geDialog.SetSizer(dbSizer)
            self.geDialog.SetBestFittingSize()
            self.geDialog.ShowModal()

    def _destroyDialog(self, evt):
        self.advanceChck.SetValue(False)
        self.geDialog.Destroy()

    def OnSetAdvancedConstraints(self, evt):
        self.constString = self.constrPnl.constrCtrl.GetValue()
        if self.constString == '':
            return
        constString = 'self.constraints=' + self.constString
        try:
            exec(constString)
            if type(self.constraints != type(list())):
                GMessage('Constraints syntax error')
                return
        except:
            GMessage('Constraints syntax error')
            return
        self.constraintsAdvanced = True
        self.geDialog.Destroy()

    def addKeyWidget(self, evt):
        name = evt.GetEventObject().GetLabel()
        if name == '+':
            kw = wx.TextCtrl(self.pnlLeft)
            addKeywordCtr = wx.Button(self.pnlLeft, -1, '-', size=(self.h, self.h))
            addKeywordCtr.Bind(wx.EVT_BUTTON, self.addKeyWidget)

            self.constraintsWidgets.append(kw)
            self.constraintsWidgets1.append(addKeywordCtr)

            self.leftSearchSizer.Add(kw, 0, wx.EXPAND)
            self.rightSearchSizer.Add(addKeywordCtr, 0)
        else:
            sizeLeft = len(self.leftSearchSizer.GetChildren())
            sizeRight = len(self.rightSearchSizer.GetChildren())

            self.constraintsWidgets.pop().Destroy()
            self.constraintsWidgets1.pop().Destroy()

            self.leftSearchSizer.Remove(sizeLeft)
            self.rightSearchSizer.Remove(sizeRight)
        self.Fit()

    def OnShowReguest(self, evt):
        request_html = encodeString(highlight_xml(self.context, self.catalog.request))
        path = 'htmlRequest.html'

        f = open(path, 'w')
        f.write(request_html)
        f.close()
        if yesNo(self, 'Do you want to open <request> in default browser', 'Open file'):
            open_url(path)
        self.htmlView.SetPage((renderXML(self.context, self.catalog.request)))

    def OnShowResponse(self, evt):
        response_html = encodeString(highlight_xml(self.context, self.catalog.response))
        path ='htmlResponse.html'
        f = open(path, 'w')
        f.write(response_html)
        f.close()
        if yesNo(self, 'Do you want to open <response> in default browser', 'Open file'):
            open_url(path)
        self.htmlView.SetPage((renderXML(self.context, self.catalog.response)))

    def OnRecord(self, evt):
        """show record metadata"""
        self.refreshServiceButt()
        curr = 0
        idx = self.resultList.GetNextItem(curr, wx.LIST_NEXT_ALL,
                                          wx.LIST_STATE_SELECTED)
        if not idx:
            return

        identifier = self.get_item_data(idx, 'identifier')
        try:
            cat = CatalogueServiceWeb(self.catalog_url, timeout=self.timeout)
            cat.getrecordbyid(
                [self.catalog.records[identifier].identifier])
        except ExceptionReport, err:
            GWarning('Error getting response: %s' % err)
            return
        except KeyError, err:
            GWarning('Record parsing error, unable to locate record identifier')
            return

        record = cat.records[identifier]
        record.xml_url = cat.request

        if self.catalog:
            path='record_metadata_dc.html'
            metadata = render_template('en', self.context,
                                       record,
                                       path)

        try:
            record = self.catalog.records[identifier]
        except KeyError, err:
            GWarning('@!Record parsing error, unable to locate record identifier')
            return

        self.htmlView.SetPage(metadata)
        self.findServices(record, idx)

    def findServices(self, record, item):
        """scan record for WMS/WMTS|WFS|WCS endpoints"""
        links = record.uris + record.references
        WMSWMST_LINK_TYPES = [
            'OGC:WMS',
            'OGC:WMTS',
            'OGC:WMS-1.1.1-http-get-map',
            'OGC:WMS-1.1.1-http-get-capabilities',
            'OGC:WMS-1.3.0-http-get-map',
            'OGC:WMS-1.3.0-http-get-capabilities',
            'urn:x-esri:specification:ServiceType:wms:url',
            'urn:x-esri:specification:ServiceType:Gmd:URL.wms'
        ]

        WFS_LINK_TYPES = [
            'OGC:WFS',
            'OGC:WFS-1.0.0-http-get-capabilities',
            'OGC:WFS-1.1.0-http-get-capabilities',
            'urn:x-esri:specification:ServiceType:wfs:url',
            'urn:x-esri:specification:ServiceType:Gmd:URL.wfs'
        ]

        WCS_LINK_TYPES = [
            'OGC:WCS',
            'OGC:WCS-1.1.0-http-get-capabilities',
            'urn:x-esri:specification:ServiceType:wcs:url',
            'urn:x-esri:specification:ServiceType:Gmd:URL.wcs'
        ]
        services = {}
        for link in links:

            if 'scheme' in link:
                link_type = link['scheme']
            elif 'protocol' in link:
                link_type = link['protocol']
            else:
                link_type = None

            if link_type is not None:
                link_type = link_type.upper()

            wmswmst_link_types = map(str.upper, WMSWMST_LINK_TYPES)
            wfs_link_types = map(str.upper, WFS_LINK_TYPES)
            wcs_link_types = map(str.upper, WCS_LINK_TYPES)

            # if the link type exists, and it is one of the acceptable
            # interactive link types, then set
            if all([link_type is not None,
                    link_type in wmswmst_link_types + wfs_link_types +
                            wcs_link_types]):
                if link_type in wmswmst_link_types:
                    services['wms'] = link['url']
                    self.bttAddWms.Enable()
                if link_type in wfs_link_types:
                    services['wfs'] = link['url']
                    self.bttAddWfs.Enable()
                if link_type in wcs_link_types:
                    services['wcs'] = link['url']
                    self.bttAddWcs.Enable()

            self.set_item_data(item, 'link', json.dumps(services))

    def refreshNavigationButt(self, stat=False):
        if stat:
            self.bttNextItem1.Enable()
            self.bttNextItem2.Enable()
            self.bttBackItem1.Enable()
            self.bttBackItem2.Enable()
            self.bttViewRequestXml.Enable()
            self.bttViewResponseXml.Enable()
        else:
            self.bttNextItem1.Disable()
            self.bttNextItem2.Disable()
            self.bttBackItem1.Disable()
            self.bttBackItem2.Disable()
            self.bttAddWms.Disable()
            self.bttAddWfs.Disable()
            self.bttAddWcs.Disable()
            self.bttViewRequestXml.Disable()
            self.bttViewResponseXml.Disable()

    def refreshServiceButt(self, stat=False):
        if not stat:
            self.bttAddWms.Disable()
            self.bttAddWfs.Disable()
            self.bttAddWcs.Disable()
        else:
            self.bttAddWms.Enable()
            self.bttAddWfs.Enable()
            self.bttAddWcs.Enable()

    def OnNavigate(self, evt):
        name = evt.GetEventObject().GetLabel()
        if name == '<<':
            self.startfrom = 0
        elif name == '>>':
            self.startfrom = self.catalog.results['matches'] - self.maxrecords
        elif name == '>':
            self.startfrom += self.maxrecords
            if self.startfrom >= self.catalog.results["matches"]:
                msg = 'End of results. Go to start?'
                if yesNo(self, msg, 'End of results'):
                    self.startfrom = 0
                else:
                    return
        elif name == '<':
            self.startfrom -= self.maxrecords
            if self.startfrom < 0:
                msg = 'Start of results. Go to end?'
                if yesNo(self, msg, 'Navigation'):
                    self.startfrom = (self.catalog.results['matches'] - self.maxrecords)
                else:
                    return

        self.loadConstraints()
        try:
            self.catalog.getrecords2(constraints=self.constraints,
                                     maxrecords=self.maxrecords,
                                     startposition=self.startfrom, esn='full')
        except ExceptionReport, err:
            GWarning('Search error: %s' % err)
            return
        except Exception, err:
            GWarning('Connection error: %s' % err)
            return

        self.displyResults()

    def OnSetCatalog(self, evt):
        val = evt.GetSelection()
        self.config.WriteInt('/guiSearch/catalog', val)

    def loadSettings(self):
        n = self.config.ReadInt('/guiSearch/catalog', 0)
        self.catalogCmb.SetSelection(n)


    def setTooltip(self, evt):
        index = evt.GetIndex()
        text = self.resultList.GetItem(index, 1)
        text = text.GetText()

        self.resultList.SetToolTip(wx.ToolTip(text))

    def setBBoxGRASS(self, evt=None):
        vdb = Module('g.region', flags='bg', stdout_=PIPE)
        vdb = parse_key_val(vdb.outputs.stdout)
        self.bbNorth.SetValue(vdb['ll_n'])
        self.bbSouth.SetValue(vdb['ll_s'])
        self.bbWest.SetValue(vdb['ll_w'])
        self.bbEast.SetValue(vdb['ll_e'])

    def setBBoxGlobal(self, evt=None):
        self.bbNorth.SetValue('90')
        self.bbSouth.SetValue('-90')
        self.bbWest.SetValue('-180')
        self.bbEast.SetValue('180')

    def _get_csw(self):
        """function to init owslib.csw.CatalogueServiceWeb"""
        # connect to the server
        try:
            self.catalog = CatalogueServiceWeb(self.catalog_url,
                                               timeout=self.timeout)
            return True
        except ExceptionReport, err:
            msg = 'Error connecting to service: %s' % err
        except ValueError, err:
            msg = 'Value Error: %s' % err
        except Exception, err:
            msg = 'Unknown Error: %s' % err
            GMessage('CSW Connection error: %s' % msg)
        return False

    def refreshResultList(self):
        self.resultList.ClearAll()
        self.resultList.InsertColumn(0, 'Type', width=wx.LIST_AUTOSIZE)
        self.resultList.InsertColumn(1, 'Service', width=300)

    def loadConstraints(self):
        if not self.advanceChck.GetValue():
            self.constraints = []
            kw = self.keywordCtr.GetValue()
            if kw:
                self.constraints.append(PropertyIsLike('csw:AnyText', kw))
            for constraint in self.constraintsWidgets:
                kw = constraint.GetValue()
                if kw != '':
                    self.constraints.append(PropertyIsLike('csw:AnyText', kw))
            if len(self.constraints) > 1:  # exclusive search (a && b)
                self.constraints = [self.constraints]
        else:
            # convert constreints to owslib object fes
            tmpConstraints = self.constraints
            for x, constraint in enumerate(tmpConstraints):
                if type(constraint) is list:
                    for y, const in enumerate(constraint):
                        self.constraints[x][y] = PropertyIsLike('csw:AnyText', const)
                    continue
                self.constraints[x] = PropertyIsLike('csw:AnyText', constraint)

    def gdalImport(self, ogr, url, type, evt):
        serviceDialog = GdalImportDialog(self, None, ogr=ogr, link=True)
        dns = serviceDialog.dsnInput
        dns.source.SetSelection(3)

        dns.SetSourceType('pro')
        if type == 'wms':
            dns.protocolWidgets['format'].SetSelection(2)
        if type == 'wcs':
            dns.protocolWidgets['format'].SetSelection(1)
        if type == 'wfs':
            dns.protocolWidgets['format'].SetSelection(2)
        dns.SetExtension(dns.protocolWidgets['format'].GetStringSelection())
        dns.protocolWidgets['text'].SetValue(url)
        dns.OnUpdate(evt)
        serviceDialog.Show()

    def OnService(self, evt):
        name = evt.GetEventObject().GetLabel()
        idx = self.resultList.GetNextItem(0, wx.LIST_NEXT_ALL,
                                          wx.LIST_STATE_SELECTED)
        if not idx:
            return
        cmd = []
        item_data = "item_data=" + self.get_item_data(idx, 'link')
        exec (item_data)
        if name == "Add WMS":
            data_url = item_data['wms']
            service = ['r.in.gdal', 'r.in.wms']
            dlg = wx.SingleChoiceDialog(
                self, 'Choice module of WMS service ', 'Service module',
                service,
                wx.CHOICEDLG_STYLE
            )

            if dlg.ShowModal() == wx.ID_OK:
                if dlg.GetStringSelection() == service[0]:
                    self.gdalImport(False, data_url, type='wms', evt=evt)
                else:
                    cmd.append('r.in.wms')
                    cmd.append('url=%s' % data_url)
                    GUI(parent=self, show=True, modal=True).ParseCommand(cmd=cmd)
            dlg.Destroy()

        elif name == "Add WFS":
            data_url = item_data['wfs']
            service = ['v.in.ogr', 'v.in.wfs']
            dlg = wx.SingleChoiceDialog(
                self, 'Choice module of WFS service ', 'Service module',
                service,
                wx.CHOICEDLG_STYLE
            )

            if dlg.ShowModal() == wx.ID_OK:
                if dlg.GetStringSelection() == service[0]:
                    self.gdalImport(True, data_url, type='wfs', evt=evt)
                else:
                    cmd.append('v.in.wfs')
                    cmd.append('url=%s' % data_url)
                    GUI(parent=self, show=True, modal=True).ParseCommand(cmd=cmd)
            dlg.Destroy()

        elif name == "Add WCS":

            data_url = item_data['wcs']
            self.gdalImport(False, data_url, type='wcs', evt=evt)


    def GetQtype(self):  # TODO need to implement
        val=self.qtypeCb.GetValue()
        if val== 'All':
            return None
        else:
            return val

    def OnSearch(self, evt):
        """execute search"""
        self.refreshResultList()
        self.catalog = None
        self.loadConstraints()
        self.catalog_url = None
        # clear all fields and disable buttons
        self.findResNumLbl.SetLabel("")

        current_text = self.catalogCmb.GetValue()
        if current_text == '':
            GMessage('Please set catalog')
            return
        key = '/connections/%s' % current_text
        self.catalog_url = self.config.Read('%s/url' % key)

        # start position and number of records to return
        self.startfrom = 0
        self.maxrecords = self.numResultsSpin.GetValue()

        # set timeout
        self.timeout = self.parent.connectionPanel.timeoutSpin.GetValue()

        # bbox
        minx = self.bbWest.GetValue()  # TODO add grass number validator
        miny = self.bbSouth.GetValue()
        maxx = self.bbEast.GetValue()
        maxy = self.bbNorth.GetValue()
        bbox = [minx, miny, maxx, maxy]

        if bbox != ['-180', '-90', '180', '90']:
            self.constraints.append(BBox(bbox))

        # (a && b)
        # build request
        if not self._get_csw():
            return

        # TODO: allow users to select resources types
        # to find ('service', 'dataset', etc.)
        # print self.constraints

        try:
            self.catalog.getrecords2(constraints=self.constraints,
                                     maxrecords=self.maxrecords, esn='full')
        except ExceptionReport, err:
            GError('Search error: %s' % err)
            return
        except Exception, err:
            GError('Connection error: %s'% err)
            return

        if self.catalog.results['matches'] == 0:
            self.findResNumLbl.SetLabel('0 results')
            return

        self.refreshNavigationButt(True)
        self.displyResults()

    def get_item_data(self, index, field):
        if field == 'identifier':
            return self.idResults[index]['identifier']
        else:
            return self.idResults[index]['link']

    def set_item_data(self, index, field, value):
        """set identifier"""

        try:
            self.idResults[index]
            idx = True
        except IndexError:
            idx = False

        if idx:
            if field == "identifier":
                self.idResults[index]['identifier'] = value
            if field == "link":
                self.idResults[index]['link'] = value
        else:
            d = {}
            if field == "identifier":
                d['identifier'] = value
            if field == "link":
                d[index]['link'] = value
            self.idResults.insert(index, d)


    def displyResults(self):
        """display search results"""

        self.refreshResultList()
        position = self.catalog.results['returned'] + self.startfrom

        msg = 'Showing %s - %s of %s result(s)' % ( self.startfrom + 1,
                                                    position,
                                                    self.catalog.results['matches'],

        )

        self.findResNumLbl.SetLabel(msg)
        index = 0
        for rec in self.catalog.records:
            if self.catalog.records[rec].type:
                item = wx.ListItem()
                self.resultList.InsertStringItem(index, normalize_text(self.catalog.records[rec].type))
            else:
                self.resultList.SetStringItem(index, 0, 'unknown')
            if self.catalog.records[rec].title:
                self.resultList.SetStringItem(index, 1, normalize_text(self.catalog.records[rec].title))

            if self.catalog.records[rec].identifier:
                self.set_item_data(index, 'identifier',
                                   self.catalog.records[rec].identifier)
            if index % 2:
                self.resultList.SetItemBackgroundColour(index, "LIGHT GREY")
            index += 1

        self.Fit()

    def onHtmlLinkClicked(self, event):
        Thread(
            target=webbrowser.open,
            args=(event.GetLinkInfo().GetHref(), 0)
        ).start()

    def updateCatalogBox(self, evt=None):
        if self.catalogCmb.GetCount() == 0:
            msg = 'No services/connections defined.'
            self.htmlView.SetPage('<p><h3>%s</h3></p>' % msg)

    def _layout(self):
        self.mainsizer = wx.BoxSizer(wx.HORIZONTAL)
        rightPanelSizer = wx.BoxSizer(wx.VERTICAL)
        leftPanelSizer = wx.BoxSizer(wx.VERTICAL)

        # search static box sizers---start
        mainSearchSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.rightSearchSizer = wx.BoxSizer(wx.VERTICAL)
        self.leftSearchSizer = wx.BoxSizer(wx.VERTICAL)
        upSearchSizer = wx.BoxSizer(wx.HORIZONTAL)

        upSearchSizer.Add(self.qtypeCb, 1, wx.EXPAND)

        self.leftSearchSizer.Add(upSearchSizer, 1 ,wx.EXPAND )
        self.rightSearchSizer.Add(wx.StaticText(self), 0)
        mainSearchSizer.Add(self.leftSearchSizer, wx.EXPAND)
        mainSearchSizer.Add(self.rightSearchSizer)

        self.leftSearchSizer.Add(self.keywordLbl, 0)

        self.rightSearchSizer.AddSpacer(4, 0, 1, wx.EXPAND)
        self.rightSearchSizer.Add(self.advanceChck, 0)

        self.leftSearchSizer.Add(self.keywordCtr, 0, wx.EXPAND)
        self.rightSearchSizer.Add(self.addKeywordCtr, 0)

        stbBox0Sizer = wx.StaticBoxSizer(self.stbSearch, wx.VERTICAL)

        self.stBox1Sizer = wx.StaticBoxSizer(self.stbFind, wx.VERTICAL)
        self.stBox1Sizer.Add(mainSearchSizer, 0, wx.EXPAND)

        # bounding box sizer---------------
        bb1sizer = wx.BoxSizer(wx.HORIZONTAL)
        bb2sizer = wx.BoxSizer(wx.HORIZONTAL)
        bb3sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.stBox2Sizer = wx.StaticBoxSizer(self.stbBB, wx.VERTICAL)
        bb1sizer.Add(self.bbWestLb)
        bb1sizer.AddSpacer(14, 10, 1, wx.EXPAND)
        bb1sizer.Add(self.bbWest, 1, wx.EXPAND)
        bb1sizer.AddSpacer(20, 10, 1, wx.EXPAND)
        bb1sizer.Add(self.bbSouthLb)
        bb1sizer.AddSpacer(14, 10, 1, wx.EXPAND)
        bb1sizer.Add(self.bbSouth, 1, wx.EXPAND)
        bb2sizer.Add(self.bbEastLb)
        bb2sizer.AddSpacer(10, 10, 1, wx.EXPAND)
        bb2sizer.Add(self.bbEast, 1, wx.EXPAND)
        bb2sizer.AddSpacer(20, 10, 1, wx.EXPAND)
        bb2sizer.Add(self.bbNorthLb)
        bb2sizer.AddSpacer(10, 10, 1, wx.EXPAND)
        bb2sizer.Add(self.bbNorth, 1, wx.EXPAND)
        bb3sizer.Add(self.bbSetGlobalBtt1, wx.EXPAND)
        bb3sizer.Add(self.bbSetMapExtendBtt1, wx.EXPAND)
        self.stBox2Sizer.Add(bb2sizer, 1, wx.EXPAND)
        self.stBox2Sizer.Add(bb1sizer, 1, wx.EXPAND)
        self.stBox2Sizer.Add(bb3sizer, 1, wx.EXPAND)
        # bounding box sizer---------------end
        stbBox0Sizer.Add(self.catalogLbl, 0)
        stbBox0Sizer.Add(self.catalogCmb, 1, wx.EXPAND)
        stbBox0Sizer.AddSpacer(10, 10, 1, wx.EXPAND)

        stbBox0Sizer.Add(self.stBox1Sizer, 0, wx.EXPAND)
        stbBox0Sizer.AddSpacer(10, 10, 1, wx.EXPAND)
        stbBox0Sizer.Add(self.stBox2Sizer, 0, wx.EXPAND)
        leftPanelSizer.Add(stbBox0Sizer, 0, wx.EXPAND)
        leftPanelSizer.AddSpacer(10, 10, 1, wx.EXPAND)

        findPanelSizer = wx.BoxSizer(wx.HORIZONTAL)

        findPanelSizer.Add(self.numResultsLbl, 0)
        findPanelSizer.Add(self.numResultsSpin, 0)

        findPanelSizer.Add(self.findBtt, 1, wx.EXPAND)
        leftPanelSizer.Add(findPanelSizer, 0, wx.EXPAND)
        leftPanelSizer.Add(self.findResNumLbl, 0)
        leftPanelSizer.Add(self.resultList, 1, wx.EXPAND)
        leftPanelSizer.AddSpacer(10, 10, 1, wx.EXPAND)

        listerSizer = wx.BoxSizer(wx.HORIZONTAL)

        listerSizer.Add(self.bttBackItem2, 1)
        listerSizer.Add(self.bttBackItem1, 1)
        listerSizer.Add(self.bttNextItem1, 1)
        listerSizer.Add(self.bttNextItem2, 1)
        leftPanelSizer.Add(listerSizer, 0, wx.EXPAND)

        rightTOPsizer = wx.BoxSizer(wx.HORIZONTAL)
        rightTOPsizer.Add(self.bttViewRequestXml)
        rightTOPsizer.Add(self.bttViewResponseXml)
        rightTOPsizer.Add(self.bttAddWms)
        rightTOPsizer.Add(self.bttAddWfs)
        rightTOPsizer.Add(self.bttAddWcs)

        rightPanelSizer.Add(rightTOPsizer)
        rightPanelSizer.Add(self.htmlView, 1, wx.EXPAND)
        self.pnlLeft.SetSizer(leftPanelSizer)
        self.pnlRight.SetSizer(rightPanelSizer)

        self.splitterBrowser.SplitVertically(self.pnlLeft, self.pnlRight)

        self.splitterBrowser.SetSashGravity(0.35)
        self.splitterBrowser.SetSashPosition(300)
        self.splitterBrowser.SetMinimumPaneSize(200)
        self.mainsizer.Add(self.splitterBrowser, 1, wx.EXPAND)
        self.SetSizerAndFit(self.mainsizer)

class CSWConnectionPanel(wx.Panel):
    def __init__(self, parent, main,cswBrowser=True):
        wx.Panel.__init__(self, parent)
        self.parent = main
        self.config = wx.Config('g.gui.cswbrowser')
        self.cswBrowser=cswBrowser
        self.splitterConn = SplitterWindow(self, style=wx.SP_3D |
                                                       wx.SP_LIVE_UPDATE | wx.SP_BORDER)
        self.panelLeft = wx.Panel(self.splitterConn, id=wx.ID_ANY)
        self.stBoxConnections = wx.StaticBox(self.panelLeft, -1, 'Connections list')
        self.stBoxConnections1 = wx.StaticBox(self.panelLeft, -1, 'Connection manager')
        self.panelRight = wx.Panel(self.splitterConn, -1)
        self.connectionLBox = wx.ListBox(self.panelLeft, id=-1, pos=wx.DefaultPosition)
        self.timeoutSpin = wx.SpinCtrl(self.panelLeft, min=1, max=100, initial=10 , style=wx.ALIGN_RIGHT | wx.SP_ARROW_KEYS)
        self.context = StaticContext()
        self.connectionFilePath = os.path.join(self.context.lib_path, 'connections_resources.xml')
        self.servicePath = 'service_metadata.html'
        self.serviceInfoBtt = wx.Button(self.panelLeft, -1, label='Service info')
        self.newBtt = wx.Button(self.panelLeft, label='New')
        self.removeBtt = wx.Button(self.panelLeft, label='Remove')
        self.setDefaultFile = wx.Button(self.panelLeft, label='Load catalog list')
        self.setDefaultFile.Bind(wx.EVT_BUTTON, self.onOpenConnFile)
        self.textMetadata = html.HtmlWindow(self.panelRight,
                                            id=-1,
                                            pos=wx.DefaultPosition,
                                            size=wx.DefaultSize,
                                            style=HW_DEFAULT_STYLE | HW_SCROLLBAR_AUTO,
                                            name="metadata")

        self.addDefaultConnections()
        self.connectionLBox.Bind(wx.EVT_LISTBOX_DCLICK, self.onServiceInfo)
        self.newBtt.Bind(wx.EVT_BUTTON, self.onNewconnection)
        self.removeBtt.Bind(wx.EVT_BUTTON, self.onRemoveConnection)
        self.serviceInfoBtt.Bind(wx.EVT_BUTTON, self.onServiceInfo)

        self.textMetadata.Bind(EVT_HTML_LINK_CLICKED, self.onHtmlLinkClicked)
        self._layout()

    def GetUrl(self):
        return self.catalog_url

    def onNewconnection(self, evt=None, cancel=False):
        if self.newBtt.GetLabel() == "New":
            self.newBtt.SetLabel('Save')
            self.newBtt.Disable()

            self.connNameNew = wx.TextCtrl(self.panelLeft)
            self.connNameNewLabel = wx.StaticText(self.panelLeft, label='Name')
            self.connNameNew.Bind(wx.EVT_TEXT, self.validateNewConn)

            self.connUrlNew = wx.TextCtrl(self.panelLeft)
            self.connUrlNewLabel = wx.StaticText(self.panelLeft, label='Url')
            self.connUrlNew.Bind(wx.EVT_TEXT, self.validateNewConn)

            self.cancelBtt = wx.Button(self.panelLeft, label="Cancel")
            self.cancelBtt.Bind(wx.EVT_BUTTON, self.cancelAddingNewURL)
            self.stBoxConnections1Sizer.Hide(1)
            self.stBoxConnections1Sizer.Add(self.cancelBtt, 1, wx.EXPAND)
            self.stBoxConnections1Sizer.Add(self.connNameNewLabel, 1, wx.EXPAND)
            self.stBoxConnections1Sizer.Add(self.connNameNew, 1, wx.EXPAND)
            self.stBoxConnections1Sizer.Add(self.connUrlNewLabel, 1, wx.EXPAND)
            self.stBoxConnections1Sizer.Add(self.connUrlNew, 1, wx.EXPAND)


        else:
            # test validity of connection
            url = self.connUrlNew.GetValue()
            if cancel:
                self.newBtt.SetLabel('New')
                self.newBtt.Enable()
                self.stBoxConnections1Sizer.Remove(self.connNameNewLabel)
                self.stBoxConnections1Sizer.Remove(self.connNameNew)
                self.stBoxConnections1Sizer.Remove(self.connUrlNewLabel)
                self.stBoxConnections1Sizer.Remove(self.connUrlNew)
                self.connNameNew.Destroy()
                self.connNameNewLabel.Destroy()
                self.connUrlNewLabel.Destroy()
                self.connUrlNew.Destroy()
                self.stBoxConnections1Sizer.Show(1)
                self.stBoxConnections1Sizer.Remove(self.cancelBtt)
                self.cancelBtt.Destroy()
                self.Fit()
                return
            if self.checkURLCSWvalidity(url):
                name = self.connNameNew.GetValue()
                if not self.addConection(name, url):
                    return
                self.newBtt.SetLabel('New')
                self.newBtt.Enable()
                self.stBoxConnections1Sizer.Remove(self.connNameNewLabel)
                self.stBoxConnections1Sizer.Remove(self.connNameNew)
                self.stBoxConnections1Sizer.Remove(self.connUrlNewLabel)
                self.stBoxConnections1Sizer.Remove(self.connUrlNew)
                self.connNameNew.Destroy()
                self.connNameNewLabel.Destroy()
                self.connUrlNewLabel.Destroy()
                self.connUrlNew.Destroy()
                self.stBoxConnections1Sizer.Show(1)
                self.stBoxConnections1Sizer.Remove(self.cancelBtt)
                self.cancelBtt.Destroy()
            else:
                GMessage('Url is not valid')

        self.Fit()

    def cancelAddingNewURL(self, evt):
        self.onNewconnection(cancel=True)

    def validateNewConn(self, evt):
        if self.connNameNew.GetValue() != '' and self.connUrlNew.GetValue() != '':
            self.newBtt.Enable()
        else:
            self.newBtt.Disable()

    def onRemoveConnection(self, evt):
        if self.connectionLBox.GetSelection() == wx.NOT_FOUND:
            GMessage('Please select catalog')
            return
        name = self.connectionLBox.GetString(self.connectionLBox.GetSelection())
        if yesNo(self, "Do you want to remove < %s > from list " % name, "Remove connection"):
            key = '/connections/%s' % name
            self.config.DeleteGroup(key)
        if yesNo(self, "Do you want to remove < %s > from default connection file " % name, "Remove connection"):
            tree = ET.parse(self.connectionFilePath)
            root = tree.getroot()
            for bad in root.findall('csw'):
                if bad.attrib['name'] == name:
                    root.remove(bad)

            tree.write(self.connectionFilePath)
            self.updateConnectionList()

    def publishCSW(self,path):
        """show connection info"""
        if self.connectionLBox.GetSelection() == wx.NOT_FOUND:
            GMessage('Please select catalog')
            return
        current_text = self.connectionLBox.GetString(self.connectionLBox.GetSelection())
        key = '/connections/%s' % current_text

        self.catalog_url = self.config.Read('%s/url' % key)

        if not self._get_csw():
            return

        if self.catalog:  # display service metadata
            metadata = render_template('en', self.context,
                                       self.catalog,
                                       self.servicePath)

        try:
            self.catalog.transaction(ttype='insert', typename='gmd:MD_Metadata', record=open(path).read())
        except Exception, e:
            GWarning('Transaction error: <%s>'%e)

    def onHtmlLinkClicked(self, event):
        Thread(
            target=webbrowser.open,
            args=(event.GetLinkInfo().GetHref(), 0)
        ).start()

    def checkURLCSWvalidity(self, url):
        self.catalog_url = url
        if not self._get_csw():
            return False
        if self.catalog:
            metadata = render_template('en', self.context,
                                       self.catalog,
                                       self.servicePath)
            if self.textMetadata.SetPage(metadata):
                return True
        return False

    def onServiceInfo(self, evt=None):
        """show connection info"""
        if self.connectionLBox.GetSelection() == wx.NOT_FOUND:
            GMessage('Please select catalog')
            return
        current_text = self.connectionLBox.GetString(self.connectionLBox.GetSelection())
        key = '/connections/%s' % current_text

        self.catalog_url = self.config.Read('%s/url' % key)

        if not self._get_csw():
            return

        if self.catalog:  # display service metadata
            metadata = render_template('en', self.context,
                                       self.catalog,
                                       self.servicePath)
            self.textMetadata.SetPage(metadata)

    def _get_csw(self):
        """function to init owslib.csw.CatalogueServiceWeb"""
        # connect to the server
        try:
            self.catalog = CatalogueServiceWeb(self.catalog_url,
                                               timeout=self.timeoutSpin.GetValue())
            return True
        except ExceptionReport, err:
            msg = 'Error connecting to service: %s' % err
        except ValueError, err:
            msg = 'Value Error: %s' % err
        except Exception, err:
            msg = 'Unknown Error: %s' % err

            GMessage('CSW Connection error: %s' % msg)
        return False

    def addDefaultConnections(self, path=None):
        """add default connections from file"""
        if path is not None:
            self.connectionFilePath = path
            if yesNo(self, "Do you want to remove temporary connections?", "Remove tmp connections"):
                self.config.DeleteGroup('/connections')

        noerr, doc =get_connections_from_file( self.connectionFilePath)
        if not noerr:
            GError(doc)

        if doc is None:
            return
        self.config.SetPath('/connections')

        for server in doc.findall('csw'):
            name = server.attrib.get('name')
            url = server.attrib.get('url')
            key = '/connections/%s' % name
            self.config.Write('%s/url' % key, url)
        self.updateConnectionList()

    def addConection(self, name, url):
        conns = [self.connectionLBox.GetString(i) for i in range(self.connectionLBox.GetCount())]

        if name in conns:
            GMessage("Name of catalog is exists, new catalog is not saved")
            n = self.connectionLBox.FindString(name)
            self.connectionLBox.SetSelection(n)
            return False
        self.config.SetPath('/connections')
        key = '/connections/%s' % name
        self.config.Write('%s/url' % key, url)
        self.updateConnectionList()
        if yesNo(self, "Do you want to add connection to default configuration file", "Default connection"):
            tree = ET.parse(self.connectionFilePath)
            root = tree.getroot()

            st = ET.Element("csw", name=name, url=url)
            root.append(st)
            tree.write(self.connectionFilePath)
        return True

    def updateConnectionList(self):

            """populate select box with connections"""
            self.connectionLBox.Clear()

            more, value, index = self.config.GetFirstGroup()
            first = value
            if self.cswBrowser:# ONLY FOR g.gui.cswbrowser
                self.parent.BrowserPanel.catalogCmb.Clear()

            while more:
                if self.cswBrowser:
                    self.parent.BrowserPanel.catalogCmb.Append(value)
                self.connectionLBox.Append(value)
                more, value, index = self.config.GetNextGroup(index)
            n = self.connectionLBox.GetCount()
            self.connectionLBox.SetString(n + 1, first)
            if self.connectionLBox.GetCount() == 0:
                msg = 'No services/connections defined.'
                self.textMetadata.SetPage('<p><h3>%s</h3></p>' % msg)
            if self.cswBrowser:
                self.parent.BrowserPanel.loadSettings()


    def onOpenConnFile(self, event):
        openFileDialog = wx.FileDialog(self, "Open catalog file", "", "",
                                       "XML files (*.xml)|*.xml", wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if openFileDialog.ShowModal() == wx.ID_CANCEL:
            return
        input_stream = openFileDialog.GetPath()
        self.addDefaultConnections(input_stream)

    def _layout(self):
        self.mainsizer = wx.BoxSizer(wx.HORIZONTAL)

        rightPanelSizer = wx.BoxSizer(wx.VERTICAL)
        self.configureSizer = wx.BoxSizer(wx.VERTICAL)
        self.stBoxConnectionsSizer = wx.StaticBoxSizer(self.stBoxConnections, wx.VERTICAL)
        self.stBoxConnectionsSizer.Add(self.connectionLBox, 1, wx.EXPAND)
        self.stBoxConnectionsSizer.AddSpacer(20, 10, 1, wx.EXPAND)
        self.stBoxConnectionsSizer.Add(wx.StaticText(self.panelLeft,label='Timeout'),0)
        self.stBoxConnectionsSizer.Add(self.timeoutSpin, 0)

        self.stBoxConnectionsSizer.Add(self.serviceInfoBtt, 0, wx.EXPAND)
        self.configureSizer.Add(self.stBoxConnectionsSizer, 1, wx.EXPAND)

        self.configureSizer.AddSpacer(20, 10, 1, wx.EXPAND)
        self.stBoxConnections1Sizer = wx.StaticBoxSizer(self.stBoxConnections1, wx.VERTICAL)
        self.stBoxConnections1Sizer.Add(self.newBtt, 0, wx.EXPAND)
        self.stBoxConnections1Sizer.Add(self.removeBtt, 0, wx.EXPAND)

        self.configureSizer.Add(self.stBoxConnections1Sizer, 0, wx.EXPAND)
        self.configureSizer.Add(self.setDefaultFile, 0, wx.EXPAND)
        rightPanelSizer.Add(self.textMetadata, 1, wx.EXPAND)

        self.panelRight.SetSizer(rightPanelSizer)
        self.panelLeft.SetSizer(self.configureSizer)

        self.splitterConn.SplitVertically(self.panelLeft, self.panelRight, sashPosition=0.8)
        self.splitterConn.SetSashGravity(0.2)
        self.splitterConn.SetMinimumPaneSize(200)
        self.mainsizer.Add(self.splitterConn, 1, wx.EXPAND)
        self.SetInitialSize()
        self.SetSizer(self.mainsizer)

class AutoWidthListCtrl(wx.ListCtrl, ListCtrlAutoWidthMixin):
    def __init__(self, parent):
        wx.ListCtrl.__init__(self, parent, -1, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        ListCtrlAutoWidthMixin.__init__(self)