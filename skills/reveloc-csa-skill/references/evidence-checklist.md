# Reveloc CSA Evidence Checklist

Use this only when the existing CSA workflow reaches the Reveloc application.

## 1. Identify the deployed application

- [ ] Product name and version confirmed
- [ ] Reveloc vs RevelocPlus naming reconciled
- [ ] Licensed/enabled modules identified
- [ ] Application servers identified
- [ ] Database host/instance/database identified
- [ ] Client types identified
- [ ] Production/non-production environments distinguished

## 2. Establish the radio-system boundary

- [ ] Radio technology confirmed (TETRA / DMR / other)
- [ ] Radio platform/vendor confirmed
- [ ] Base station/node/core components identified
- [ ] Radio terminal models identified
- [ ] Reveloc integration point confirmed
- [ ] GPS information source confirmed
- [ ] RSSI information source confirmed
- [ ] Telemetry/events supplied to Reveloc confirmed
- [ ] Alert/action path from Reveloc back to radio confirmed

## 3. Current functionality

For each item mark: `Enabled`, `Not enabled`, `Not established`.

- [ ] Live radio/asset location
- [ ] Historic replay
- [ ] RSSI heat mapping
- [ ] Network/coverage analysis
- [ ] Speed alerting
- [ ] Exclusion/confinement geofencing
- [ ] Blast zone warning
- [ ] Emergency zone management
- [ ] Channel Assist / location-driven channel or talkgroup change
- [ ] Keep Alive Monitoring
- [ ] Asset Validation
- [ ] Log KPI Extractor
- [ ] RevBroadcast
- [ ] RevWeatherWatch
- [ ] RevPrestart
- [ ] Other custom integration

## 4. Hosting and infrastructure

- [ ] Server names
- [ ] OS/version
- [ ] VM/hypervisor/physical hosting
- [ ] site/data-centre location
- [ ] CPU/RAM/storage
- [ ] application redundancy
- [ ] database redundancy
- [ ] backup and restore
- [ ] DR arrangement
- [ ] NTP/time source
- [ ] DNS use
- [ ] service accounts
- [ ] certificates, where applicable

## 5. Connectivity

- [ ] VLAN/subnet/security zone
- [ ] firewall flows
- [ ] ports/protocols
- [ ] WAN/MPLS dependency
- [ ] radio-core dependency
- [ ] client access path
- [ ] external integrations
- [ ] monitoring path

## 6. Data

- [ ] location history
- [ ] RSSI history
- [ ] telemetry fields
- [ ] radio identity mapping
- [ ] asset mapping
- [ ] geofence/map data
- [ ] event/alarm history
- [ ] retention period
- [ ] database backup retention
- [ ] external exports/feeds

## 7. Operations and support

- [ ] business owner
- [ ] application owner
- [ ] telecommunications/radio support owner
- [ ] infrastructure owner
- [ ] database owner
- [ ] vendor support
- [ ] monitoring
- [ ] incident process
- [ ] patching
- [ ] application upgrades
- [ ] radio configuration change process
- [ ] geofence/change approval process
- [ ] user/access management

## 8. Failure behaviour

Evidence or SME confirmation should establish:

- [ ] impact of Reveloc server failure
- [ ] impact of database failure
- [ ] impact of a single radio site/node failure
- [ ] impact of TETRA/DMR core failure
- [ ] impact of WAN/MPLS loss
- [ ] impact of GPS loss/stale positions
- [ ] impact of DNS loss where used
- [ ] impact of NTP/time-sync loss
- [ ] alert behaviour during partial outage
- [ ] recovery/start-up order
- [ ] whether core voice communication remains available when Reveloc is unavailable

## 9. Language check before writing

- [ ] Reveloc is not incorrectly described as the radio network
- [ ] TETRA is not incorrectly described as Reveloc
- [ ] GPS and RSSI are distinguished
- [ ] vendor-supported capability is not presented as deployed functionality
- [ ] geofence alerting is not called a safety interlock without evidence
- [ ] historical Aurizon architecture is not presented as current without evidence
- [ ] the narrative describes the system/application, not merely the evidence tables
