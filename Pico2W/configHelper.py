#Copyright 2022-2025 Hugh Garner
#Permission is hereby granted, free of charge, to any person obtaining a copy 
#of this software and associated documentation files (the "Software"), to deal 
#in the Software without restriction, including without limitation the rights 
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell 
#copies of the Software, and to permit persons to whom the Software is 
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in 
#all copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR 
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, 
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL 
#THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR 
#OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, 
#ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR 
#OTHER DEALINGS IN THE SOFTWARE. 
#v2.01 12/30/2024 Default showLog to True
#v2.00 11/30/2024 Add Toggle test type

def loadRequired(filename='requiredConfigItems.py',showLog=True):
    success = True
    requiredConfigNames = []
    requiredConfigTests = []
    validPins = []
    validSDAs = [[],[]]
    validSCLs = [[],[]]
    validI2Cs = []
    validStateMachines = []
    try:
        # Open the config.py file for reading
        with open(filename, 'r') as config_file:
            # Initialize empty lists
            requiredConfigNames = [value for value in config_file.readline().strip().split(',')]
            requiredConfigTests = [value for value in config_file.readline().strip().split(',')]
            validPins = [int(pin) for pin in config_file.readline().strip().split(',')]
            sets = config_file.readline().strip().split(';')
            for i, set_values in enumerate(sets):
                values = set_values.strip().split(',')
                validSDAs[i] = [int(value) for value in values]
            sets = config_file.readline().strip().split(';')
            for i, set_values in enumerate(sets):
                values = set_values.strip().split(',')
                validSCLs[i] = [int(value) for value in values]
            validI2Cs = [int(i) for i in config_file.readline().strip().split(',')]
            validStateMachines = [int(i) for i in config_file.readline().strip().split(',')]
    except OSError as e:
        if showLog:
            print("Error reading file " + filename + ":",e)
        success = False
    except ValueError as e:
        if showLog:
            print("Invalid format in the " + filename + " file:",e)
        success = False
    return (success,requiredConfigNames,requiredConfigTests,validPins,validSDAs,validSCLs,validI2Cs,validStateMachines)

def readConfigFile(filename,showLog=True):
    config = ""
    with open(filename,"r") as file:
        config = file.readlines()
    return config
        
def writeConfigFile(config,filename,showLog=True):
    with open(filename,"w") as file:
        for line in config:
            file.write(line)
    if showLog:
        print(f"Config written to {filename}.")

def validateConfig(config,requiredConfigNames,requiredConfigTests,validPins,validSDAs,validSCLs,validI2Cs,validStateMachines,showLog=True):
    configArray = []
    for item in config:
        configArray.append(item)
    return validateConfigArray(configArray,requiredConfigNames,requiredConfigTests,validPins,validSDAs,validSCLs,validI2Cs,validStateMachines,showLog)
def validateConfigArray(configArray,requiredConfigNames,requiredConfigTests,validPins,validSDAs,validSCLs,validI2Cs,validStateMachines,showLog=True):
    validated = True
    errors = []
    
    attributes = []
    values = []
    for item in configArray:
        item = item.strip()
        parts = item.split('=')
        if len(parts) == 2:
            attribute = parts[0].strip()
            value = parts[1].strip()
            
            attributes.append(attribute)
            values.append(value)

            if attribute in requiredConfigNames:
                pos = requiredConfigNames.index(attribute)
                test = requiredConfigTests[pos]
                
                if test == "PORT":
                    if not value.isdigit() or not (0 <= int(value) <= 65535):
                        errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                        validated = False
                elif test == "PIN":
                    if not value.isdigit() or int(value) not in validPins:
                        errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                        validated = False
                elif test == "TIME":
                    if not value.isdigit() or not (1 <= int(value) <= 60000):
                        errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                        validated = False
                elif test == "SDA":
                    if not value.isdigit() or int(value) not in validSDAs[0] and int(value) not in validSDAs[1]:
                        errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                        validated = False
                elif test == "SCL":
                    if not value.isdigit() or int(value) not in validSCLs[0] and int(value) not in validSCLs[1]:
                        errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                        validated = False
                elif test == "I2C":
                    if not value.isdigit() or int(value) not in validI2Cs:
                        errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                        validated = False
                elif test == "INT":
                    if not value.isdigit() or int(value) < 0:
                        errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                        validated = False
                elif test == "SM":
                    if not value.isdigit() or int(value) not in validStateMachines:
                        errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                        validated = False
                elif test == "LEDS":
                    led_ranges = value.replace('"','').split(";")
                    for led_range in led_ranges:
                        start, end = led_range.split("-")
                        if not start.isdigit() or not end.isdigit():
                            errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                            validated = False
                            break
                        start, end = int(start), int(end)
                        if not (0 <= start <= end <= 500):
                            errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                            validated = False
                            break
                elif test == "TOGGLE":
                    if not value.isdigit() or int(value) < 0 or int(value) > 1:
                        errors.append(f"Error: {value} invalid for {attribute} in the config module.")
                        validated = False
            else:
                errors.append(f"Error: Unknown attribute {attribute} in the config module.")
                validated = False

    missing_items = [item for item in requiredConfigNames if item not in attributes]
    if missing_items:
        for item_name in missing_items:
            errors.append(f"Error: {item_name} is missing from the config module.")

    # Check for duplicate attribute values with the same test
    attribute_value_map = {}
    skip_tests = {"TIME","LEDS"}
    for attribute, value in zip(attributes, values):
        if attribute in requiredConfigNames:
            test = requiredConfigTests[requiredConfigNames.index(attribute)]
            if test in skip_tests:
                continue
            key = (test, value)
            if key in attribute_value_map:
                attribute_value_map[key].append(attribute)
            else:
                attribute_value_map[key] = [attribute]
    
    for (test, value), attributes in attribute_value_map.items():
        if len(attributes) > 1:
            attributes_str = ", ".join(attributes)
            errors.append(f"Error: Duplicated value '{value}' found in attributes: {attributes_str}.")

    for error in errors:
        if showLog:
            print(error)

    return validated
