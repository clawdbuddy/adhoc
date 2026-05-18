# Config Layer Test Cases (TC-CFG-001 ~ TC-CFG-010)

## TC-CFG-001: parse_conf_file parses standard key=value

**Priority**: P0
**Type**: Unit
**Estimated Time**: 1 min

**Prerequisites**:
- Python 3.13+, pytest installed
- Working directory: `manet-30ns3/`

**Test Steps**:
1. Create a temporary `.conf` file with: `nNodes = 8\nfrequencyMhz = 5180\n`
2. Call `parse_conf_file(path)`
3. Assert the result equals `{"nNodes": 8, "frequencyMhz": 5180}`

**Expected Result**:
✅ `nNodes` parsed as int 8, `frequencyMhz` parsed as int 5180

**Pass/Fail Criteria**:
- ✅ PASS: Both keys parsed correctly with correct types
- ❌ FAIL: Type coercion wrong or key missing

---

## TC-CFG-002: parse_conf_file ignores // comments and empty lines

**Priority**: P0
**Type**: Unit
**Estimated Time**: 1 min

**Prerequisites**:
- Python 3.13+, pytest installed

**Test Steps**:
1. Create a `.conf` file with:
   ```
   // comment
   nNodes = 3  // inline comment

   // empty line above
   ssid = "test-net"
   ```
2. Call `parse_conf_file(path)`
3. Assert result is `{"nNodes": 3, "ssid": "test-net"}`

**Expected Result**:
✅ Comments stripped, empty lines ignored, only valid key=value pairs returned

---

## TC-CFG-003: parse_conf_file converts legacy aliases pcapTracing→pcap, asciiTracing→ascii

**Priority**: P0
**Type**: Unit
**Estimated Time**: 1 min

**Prerequisites**:
- Python 3.13+, pytest installed

**Test Steps**:
1. Create a `.conf` with: `pcapTracing = true\nasciiTracing = false\n`
2. Call `parse_conf_file(path)`
3. Assert result is `{"pcap": True, "ascii": False}`

**Expected Result**:
✅ Legacy aliases correctly mapped to new keys

---

## TC-CFG-004: load_config priority — overrides > file > preset > defaults

**Priority**: P0
**Type**: Unit
**Estimated Time**: 1 min

**Prerequisites**:
- Python 3.13+, pytest installed

**Test Steps**:
1. Create file with `nNodes = 12`
2. Call `load_config(file_path=path, overrides={"nNodes": 3}, preset="debug")`
3. Assert `cfg.n_nodes == 3`

**Expected Result**:
✅ overrides (3) wins over file (12) and preset default (5)

---

## TC-CFG-005: load_config accepts both snake_case and camelCase overrides

**Priority**: P1
**Type**: Unit
**Estimated Time**: 1 min

**Test Steps**:
1. `load_config(overrides={"frequency_mhz": 5900})` — snake_case
2. `load_config(overrides={"frequencyMhz": 5180})` — camelCase
3. Assert both produce correct values

**Expected Result**:
✅ Both formats accepted, same result

---

## TC-CFG-006: SimConfig.merged_with merges partial overrides

**Priority**: P1
**Type**: Unit
**Estimated Time**: 1 min

**Test Steps**:
1. Create `SimConfig()` with defaults
2. Call `cfg.merged_with({"n_nodes": 10})`
3. Assert `merged.n_nodes == 10` and other fields unchanged

**Expected Result**:
✅ Partial merge works, untouched fields retain defaults

---

## TC-CFG-007: All 12 presets load and have required fields

**Priority**: P1
**Type**: Unit
**Estimated Time**: 1 min

**Test Steps**:
1. Iterate all entries in `PRESETS`
2. Assert each is a `SimConfig` instance with `n_nodes >= 2`

**Expected Result**:
✅ All 12 presets (default, urban, rural, debug, throughput, tactical, wifi-*) valid

---

## TC-CFG-008: mac_mode="adhoc" is forced to "mesh"

**Priority**: P0
**Type**: Unit
**Estimated Time**: 1 min

**Test Steps**:
1. `cfg = SimConfig(mac_mode="adhoc")`
2. Assert `cfg.mac_mode == "mesh"`

**Expected Result**:
✅ NS-3.47 + cppyy incompatibility workaround active

---

## TC-CFG-009: SimConfig.model_dump(by_alias=True) outputs camelCase

**Priority**: P2
**Type**: Unit
**Estimated Time**: 1 min

**Test Steps**:
1. `dumped = SimConfig().model_dump(by_alias=True)`
2. Assert `"nNodes"` in dumped, `"simulationTime"` in dumped
3. Assert no snake_case keys

**Expected Result**:
✅ All keys are camelCase when serialized for API/JSON

---

## TC-CFG-010: FIELD_DESCRIPTIONS keys are in sync with SimConfig fields

**Priority**: P3
**Type**: Unit
**Estimated Time**: 1 min

**Test Steps**:
1. Collect all SimConfig field names via `model_fields`
2. Check all field names exist in `FIELD_DESCRIPTIONS`

**Expected Result**:
✅ Every field has a description entry (no silent omission)

---