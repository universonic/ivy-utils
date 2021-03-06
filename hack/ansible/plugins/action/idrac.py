from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import ssl
import urllib2
import json
import subprocess

from ansible.plugins.action import ActionBase

class ActionModule(ActionBase):
    '''Dell PowerEdge iDrac Management Action Module for Ansible
    '''

    def run(self, tmp=None, task_vars=None):

        if task_vars is None:
            task_vars = dict()

        result = super(ActionModule, self).run(tmp, task_vars)
        del tmp # tmp no longer has any effect

        # TODO: args parsers here
        idrac_addr = task_vars["idrac_addr"]
        idrac_user = task_vars["idrac_user"]
        idrac_pass = task_vars["idrac_pass"]

        # TODO: args validators here

        result['changed'] = False
        facts = dict() # initial a new dict pointer to store bundled results
        result['ansible_facts'] = facts
        facts['idrac_address'] = idrac_addr

        manager = IDracManager(
            idrac_addr=idrac_addr,
            idrac_user=idrac_user,
            idrac_pass=idrac_pass
        )
        # OPTIMIZE: use async workers
        power_state = manager.get_power_state()
        facts['idrac_model'] = copy_from_dict_in_peace("Model", power_state)
        facts['idrac_bios_version'] = copy_from_dict_in_peace("BiosVersion", power_state)
        facts['idrac_bios_boot_mode'] = manager.bios_boot_mode
        facts['idrac_hostname'] = copy_from_dict_in_peace("HostName", power_state)
        system_location = manager.get_system_location()
        facts['idrac_system_location_aisle'] = copy_from_dict_in_peace("Aisle", system_location)
        facts['idrac_system_location_datacenter'] = copy_from_dict_in_peace("DataCenter", system_location)
        facts['idrac_system_location_rack_name'] = copy_from_dict_in_peace("Rack.Name", system_location)
        facts['idrac_system_location_rack_slot'] = copy_from_dict_in_peace("Rack.Slot", system_location)
        facts['idrac_system_location_room_name'] = copy_from_dict_in_peace("RoomName", system_location)
        facts['idrac_device_size'] = copy_from_dict_in_peace("DeviceSize", system_location)
        mem_settings = manager.get_mem_settings()
        facts['idrac_installed_memory'] = copy_from_dict_in_peace("SysMemSize", mem_settings)
        hwinventory = manager.get_hardware_inventory()
        try:
            facts['idrac_maximum_dimm'] = int(hwinventory['System']['Embedded.1']['MaxDIMMSlots'])
            facts['idrac_populated_dimm'] = int(hwinventory['System']['Embedded.1']['PopulatedDIMMSlots'])
        except KeyError:
            facts['idrac_populated_dimm'] = None
            facts['idrac_maximum_dimm'] = None
        dimm_inventory = []
        facts['idrac_dimm_inventory'] = dimm_inventory
        if 'DIMM' in hwinventory:
            for each in hwinventory['DIMM'].values():
                newItem = dict()
                try:
                    newItem['name'] = each['DeviceDescription']
                    newItem['manufacturer'] = each['Manufacturer']
                    newItem['type'] = each['MemoryType']
                    newItem['model'] = each['Model']
                    newItem['part_number'] = each['PartNumber']
                    newItem['status'] = each['PrimaryStatus']
                    newItem['serial_number'] = each['SerialNumber']
                    newItem['size'] = each['Size']
                    newItem['speed'] = each['Speed']
                except KeyError:
                    continue
                dimm_inventory.append(newItem)
        vdisk_facts = []
        pdisk_facts = []
        facts['idrac_virtual_disks'] = vdisk_facts
        facts['idrac_physical_disks'] = pdisk_facts
        if 'Disk' in hwinventory:
            for each in hwinventory['Disk'].values():
                newDisk = dict()
                try:
                    if each['Device Type'] == 'PhysicalDisk':
                        newDisk['name'] = each['Model']
                        newDisk['description'] = each['DeviceDescription']
                        newDisk['status'] = each['PrimaryStatus']
                        newDisk['state'] = each['RaidStatus']
                        newDisk['serial_number'] = each['SerialNumber']
                        size = each['SizeInBytes'].split()
                        newDisk['size'] = sizeof_fmt(int(size[0]))
                        newDisk['media_type'] = each['MediaType']
                        pdisk_facts.append(newDisk)
                    elif each['Device Type'] == 'VirtualDisk':
                        newDisk['name'] = each['Name']
                        newDisk['description'] = each['DeviceDescription']
                        newDisk['status'] = each['PrimaryStatus']
                        newDisk['state'] = each['RAIDStatus']
                        newDisk['layout'] = each['RAIDTypes']
                        size = each['SizeInBytes'].split()
                        newDisk['size'] = sizeof_fmt(int(size[0]))
                        newDisk['media_type'] = each['MediaType']
                        vdisk_facts.append(newDisk)
                except KeyError:
                    continue

        try:
            facts['ansible_department'] = task_vars['department']
        except KeyError:
            facts['ansible_department'] = 'N/A'
        try:
            facts['ansible_comment'] = task_vars['comment']
        except KeyError:
            facts['ansible_comment'] = ''

        return result

class IDracManager:
    '''IDracManager is a light weight HTTP caller to Dell PowerEdge iDrac Restful API
    '''

    def __init__(self, idrac_addr, idrac_user, idrac_pass):
        self._idrac_addr = idrac_addr
        self._idrac_user = idrac_user
        self._idrac_pass = idrac_pass

    @property
    def bios_boot_mode(self):
        '''Retrieve server BIOS boot mode. It is a shorthand of get_bios() indeed.

        readonly property
        '''
        result = ''
        try:
            result = self.get_bios()[u'Attributes']["BootMode"]
        except:
            result = ''
        return result
    
    def get_power_state(self):
        return self._request_in_peace()

    def get_bios(self):
        return self._request_in_peace('Bios')

    def get_boot_sources(self):
        return self._request_in_peace('BootSources')

    def get_ethernet_interface(self, nic=None):
        if nic:
            return self._request_in_peace('EthernetInterfaces/%s' % nic)
        return self._request_in_peace('EthernetInterfaces')

    def get_storage_controller(self, ctlr=None):
        if ctlr:
            return self._request_in_peace('Storage/Controllers/%s' % ctlr)
        return self._request_in_peace('Storage/Controllers')

    def get_firmware_inventory(self, dev=None):
        if dev:
            return self._request_in_peace(route_suffix='FirmwareInventory/%s' % dev, route_namespace='UpdateService')
        return self._request_in_peace(route_suffix='FirmwareInventory', route_namespace='UpdateService')

    def get_lifecycle_logs(self):
        return self._request_in_peace(route_suffix='Logs/Lclog', route_namespace='Managers/iDRAC.Embedded.1')

    def get_attribute_group(self, grp='idrac'):
        result = dict()
        if grp == "idrac":
            result = self._request_in_peace(route_suffix='Attributes', route_namespace='Managers/iDRAC.Embedded.1')
        elif grp == "lc":
            result = self._request_in_peace(route_suffix='Attributes', route_namespace='Managers/LifecycleController.Embedded.1')
        elif grp == "system":
            result = self._request_in_peace(route_suffix='Attributes', route_namespace='Managers/System.Embedded.1')
        return result[u'Attributes']

    def get_system_location(self):
        return self._call_racadm_kv(namespace="System.Location")
    
    def get_mem_settings(self):
        return self._call_racadm_kv(namespace="BIOS.MemSettings")

    def get_mem_sensor_info(self):
        output = self._invoke_racadm(subcommand="getsensorinfo")
        qualified_result = dict()
        started = False
        skipped_header = False
        i = 0
        for line in output:
            if line == 'Sensor Type : MEMORY':
                started = True
                continue
            if not started:
                continue
            if not skipped_header:
                skipped_header = True
                continue
            if started and line.startswith('Sensor Type :'):
                break
            d = line.split()
            entity = dict()
            if len(d) == 6:
                entity['sensor_name'] = d[0] + ' ' + d[1]
                entity['status'] = d[2]
                entity['state'] = d[3]
                entity['lc'] = d[4]
                entity['uc'] = d[5]
            elif len(d) == 5:
                entity['sensor_name'] = d[0]
                entity['status'] = d[1]
                entity['state'] = d[2]
                entity['lc'] = d[3]
                entity['uc'] = d[4]
            if entity:
                qualified_result[i] = entity
                i += 1
        return qualified_result

    def get_hardware_inventory(self):
        output = self._invoke_racadm('hwinventory', None)
        qualified_result = dict()
        started = False
        group = ''
        header = ''
        sections = -1
        for line in output:
            if not started:
                if line.startswith('----'):
                    started = True
                continue
            if line.startswith('[InstanceID: '):
                sections += 1
                title = line[13:len(line)-1]
                ss = title.split('.', 1)
                group = ss[0]
                header = ss[1]
                if not group in qualified_result:
                    qualified_result[group] = dict()
                if not header in qualified_result[group]:
                    qualified_result[group][header] = dict()
                continue
            if not line or not '=' in line:
                continue
            kv = line.split('=')
            k = kv[0].strip()
            v = kv[1].strip()
            qualified_result[group][header][k] = v
        return qualified_result

    def get_virtual_disks(self):
        output = self._invoke_racadm('storage', None, 'get', 'vdisks', '-o')
        qualified_result = dict()
        i = -1
        for line in output:
            if line.startswith('Disk'):
                i += 1
                qualified_result[i] = dict()
                continue
            if not '=' in line:
                continue
            kv_orig = line.split('=')
            k = kv_orig[0].strip()
            v = kv_orig[1].strip()
            qualified_result[i][k] = v
        return qualified_result

    def get_physical_disks(self):
        output = self._invoke_racadm('storage', None, 'get', 'pdisks', '-o')
        qualified_result = dict()
        i = -1
        for line in output:
            if line.startswith('Disk'):
                i += 1
                qualified_result[i] = dict()
                continue
            if not '=' in line:
                continue
            kv_orig = line.split('=')
            k = kv_orig[0].strip()
            v = kv_orig[1].strip()
            qualified_result[i][k] = v
        return qualified_result

    def _request_in_peace(self, route_suffix=None, route_namespace='Systems/System.Embedded.1'):
        url = 'https://%s/redfish/v1/%s/' % (self._idrac_addr, route_namespace)
        if route_suffix:
            url += route_suffix

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        global retries
        retries = 0
        def acquire():
            try:
                req = urllib2.Request(url=url, headers=self._construct_headers())
                resp = urllib2.urlopen(req, context=ctx)
                body = resp.read()
                resp.close()
                return json.loads(body)
            except:
                global retries
                if retries <= 2:
                    retries += 1
                    return acquire()
                return dict()
        return acquire()
        
    def _call_racadm_kv(self, subcommand="get", namespace=None):
        output = self._invoke_racadm(subcommand, namespace)
        qualified_output = dict()
        for i in output:
            if "=" in i:
                kv = i.split('=')
                k = kv[0]
                v = kv[1]
                if k.startswith('#'):
                    k = k[1:]
                qualified_output[k] = v
        return qualified_output

    def _invoke_racadm(self, subcommand="get", namespace=None, *args):
        cmd = ["racadm", "-r", self._idrac_addr, "-u", self._idrac_user, "-p", self._idrac_pass, "--nocertwarn", subcommand]
        if namespace:
            cmd.append(namespace)
        for i in args:
            cmd.append(i)
        output = []
        try:
            output = subprocess.check_output(cmd).strip().split('\r\n')
        except subprocess.CalledProcessError as e:
            if e.returncode != 1:
                print('An unexceptable error just occurred. You should check the state of node through remote IPMI interface immediately.')
                raise e
            else:
                output = []
        if len(output) == 1:
            output = output[0].split('\n')
        return output

    def _construct_headers(self):
        headers = dict()
        credential = '%s:%s' % (self._idrac_user, self._idrac_pass)
        headers['Authorization'] = 'Basic %s' % (credential.encode('base64')[:-1])
        return headers

def copy_from_dict_in_peace(key, dictionary):
    v = ''
    try:
        v = dictionary[key]
    except KeyError:
        v = 'N/A'
    return v

def sizeof_fmt(num, suffix='B'):
    '''
    Calculate given numeber of bytes to human-readable.
    '''
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f %s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f %s%s" % (num, 'Yi', suffix)