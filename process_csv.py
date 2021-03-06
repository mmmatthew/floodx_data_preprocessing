# This script manages the pre-processing of floodX data to make it easily readable, by humans and machines
#
# Steps:
#  - read settings
#  - read sensor list
#  - for each sensor, check if output file was already generated
#  - only reprocess the data if the overwrite setting is set to True
#  - for reprocessing a sensor X's data
#    - find all data sources for sensor X
#    - create a temporary table T in which to store data
#    - for each data source, read the data into T, at the same time reformatting datetime and nodata
#    - shift the data to realign
#    - sort the table by datetime
#    - write the table as a csv


# PACKAGES
import pandas as pd
import math
import os
import glob
import datetime
import settings as s
from Tkinter import *

# READ LIST OF SENSORS
datasource_list = pd.read_csv(
    filepath_or_buffer=s.input['sensor_list_path'],
    sep=s.input['separator']
)

# READ METADATA
datasource_files = pd.read_csv(
    filepath_or_buffer=s.input['datasource_files_path'],
    sep=s.input['separator'],
    keep_default_na=False
)

# Refine sensor list
#  check if datasource_files is ok
datasource_list = datasource_list[datasource_list['metadata'] == 'ok']

gui_master = Tk()
do_preprocess = dict()


def start_gui():

    # Create dialog iteratively
    for index, row in datasource_list.iterrows():
        do_preprocess[row['datasource']] = IntVar()
        Checkbutton(gui_master, text=row['datasource'], variable=do_preprocess[row['datasource']]).grid(row=index+5, sticky=W)
    Button(gui_master, text='Select all', command=selectAll).grid(row=3, sticky=W, pady=4)
    Button(gui_master, text='Deselect all', command=deselectAll).grid(row=4, sticky=W, pady=4)
    Button(gui_master, text='Process data', command=process).grid(row=2, sticky=W, pady=4)
    Button(gui_master, text='Cancel', command=quit).grid(row=1, sticky=W, pady=4)
    gui_master.lift()
    mainloop()


def selectAll():
    for datasource in do_preprocess:
        do_preprocess[datasource].set(1)


def deselectAll():
    for datasource in do_preprocess:
        do_preprocess[datasource].set(0)


def process():

    # Close GUI
    gui_master.destroy()

    # LOOP THROUGH SENSORS
    for index, row in datasource_list.iterrows():

        current_datasource = row['datasource']

        # check if the sensor was selected to be processed
        if do_preprocess[current_datasource].get() == 1:

            print current_datasource

            # create temporary table
            temp_dataframe = pd.DataFrame({
                'datetime': [],
                'value': []
            })

            # find files linked to datasources
            datasource_file = datasource_files[datasource_files['datasource'] == current_datasource]
            if len(datasource_file.index) == 0:
                print 'WARNING: No files associated to current datasource. Please check metadata'
            for index2, datasource in datasource_file.iterrows():
                print '  ' + datasource['filename_pattern']
                newdata = read_csv_to_dataframe(datasource)
                temp_dataframe = pd.concat([temp_dataframe, newdata])

            # SORT THE DATAFRAME BY DATETIME
            temp_dataframe = temp_dataframe.sort_values(by='datetime', ascending=True)

            # REMOVE BAD VALUES
            if not row['removal_mask'] == ' ':
                temp_dataframe = remove_values(temp_dataframe, os.path.join(s.input['metadata_dir'], row['removal_mask']))

            # ADD COLUMN WITH SENSOR NAME
            temp_dataframe['sensor'] = current_datasource

            # SAVE DATA
            if s.output['export_selection'] == 'all_data':
                save_data(temp_dataframe, current_datasource, series_name='all')
            else:
                save_data_by_experiment(temp_dataframe, current_datasource, s.output['export_selection'])


def save_data_by_experiment(data, current_sensor, selection):

    # Read list of experiments
    experiment_list = pd.read_csv(
        filepath_or_buffer=s.input['experiment_list_path'],
        sep=s.input['separator']
    )

    # Filter list
    if selection == 'calibration':
        experiment_list_filtered = experiment_list[experiment_list['experiment_quality'] == 'calibration']
    elif selection == 'monitoring':
        experiment_list_filtered = experiment_list[(experiment_list['experiment_quality'] != 'insufficient')]

    # For each experiment, extract and save data
    for index, experiment in experiment_list_filtered.iterrows():
        # Find start and end datetimes
        start = pd.to_datetime(experiment['start_datetime'], format='%d.%m.%y %H:%M')
        end = pd.to_datetime(experiment['end_datetime'], format='%d.%m.%y %H:%M')
        # Extract data
        experiment_data = data[(data['datetime'] <= end) & (data['datetime'] >= start)]
        # Tag extracted data with experiment name
        experiment_data.is_copy = False
        experiment_data['experiment'] = str(experiment['id'])
        # Save data
        save_data(experiment_data, current_sensor, series_name=str(experiment['id']))

def remove_values(data, mask_file):
    # read list of periods to remove
    mask_list = pd.read_csv(
        filepath_or_buffer= mask_file,
        sep=';'
    )
    for index, row in mask_list.iterrows():
        start = pd.to_datetime(row['start'], format='%d.%m.%y %H:%M:%S')
        end = pd.to_datetime(row['end'], format='%d.%m.%y %H:%M:%S')
        data.loc[(data['datetime'] <= end) & (data['datetime'] >= start), 'value'] = 0

    return data

def read_csv_to_dataframe(datasource):
    # read csv(s) into temporary table
    temp_dataframe = pd.DataFrame({
        'datetime': [],
        'value': []
    })

    # list of matching files
    files = glob.glob(os.path.join(s.input['raw_data_dir'], datasource['filename_pattern']))

    datetime_col_names = filter(bool, [
        datasource['date_col'],
        datasource['time_col'],
        datasource['datetime_col']
    ])

    if len(files) == 0:
        print 'WARNING: No files found that match datasource_files pattern'

    # for each file, load data into dataframe
    for fn in files:

        # read data into temp
        temp = pd.read_csv(
            sep=datasource['separator'],
            filepath_or_buffer=fn,
            usecols=datetime_col_names + [datasource['data_col']],
            parse_dates={'dt': datetime_col_names},  # list of lists --> combine columns
            date_parser=lambda date: pd.datetime.strptime(date.strip(), datasource['datetime_format']),
            na_values=datasource['nodata_vals'].split(),
            engine='python'
        )
        # rename columns
        temp.columns = ['datetime', 'value']

        # drop lines with na
        temp = temp.dropna()

        # Remove data greater than maximum value
        if not datasource['max_valid_value'] == '':
            temp = temp[temp.value <= float(datasource['max_valid_value'])]

        # For ultrasonic sensors that contain raw values, use ground level to compute water level
        if not datasource['ground_level'] == '':
            temp.value = float(datasource['ground_level']) - temp.value

        # Apply floor value when relevant (e.g. replace anything below 3 with 3)
        if not datasource['floor_value'] == '':
            temp.loc[temp.value <= float(datasource['floor_value']), 'value'] = float(datasource['floor_value'])

        # SHIFT TIME
        # the minus sign is important
        temp['datetime'] = temp['datetime'] - parse_timedelta(datasource['time_shift'])

        # concatenate it to dataframe
        temp_dataframe = pd.concat([temp_dataframe, temp])

    return temp_dataframe


def parse_timedelta(time_str):
    regex = re.compile(r'(?P<sign>[-]?)(?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d+)')
    parts = regex.match(time_str)
    if not parts:
        return
    parts = parts.groupdict()
    parts = {
        'hours': parts['sign'] + parts['hours'],
        'minutes': parts['sign'] + parts['minutes'],
        'seconds': parts['sign'] + parts['seconds']
    }
    time_params = {}
    for (name, param) in parts.iteritems():
        if param:
            time_params[name] = int(param)
    return datetime.timedelta(**time_params)


def save_data(data_to_save, current_sensor, series_name):
    # File names
    basename = series_name + '_' + current_sensor
    output_file_csv = os.path.join(s.output['data_dir'], 'csv', series_name, basename + '.txt')
    output_file_json_temp = os.path.join(s.output['data_dir'], 'json', series_name, basename + '.json_temp')
    output_file_json = os.path.join(s.output['data_dir'], 'json', series_name, basename + '.json')

    # Check that output paths are ok. Create directories if missing
    for path in [
        s.proc['ocr_results_path'],
        os.path.join(s.output['data_dir'], 'csv', series_name),
        os.path.join(s.output['data_dir'], 'json', series_name)
    ]:
        if not os.path.exists(path):
            print "INFO: %s not found. Creating directory." % path
            os.makedirs(path)

    # SAVE TO CSV
    data_to_save.to_csv(
        path_or_buf=output_file_csv,
        sep=';',
        columns=['datetime', 'value'],
        date_format=s.output['date_format'],
        index=False
    )

    if s.output['write_crateDB']:
        # SAVE TO JSON
        data_to_save.to_json(
            path_or_buf=output_file_json_temp,
            orient='records'
        )

        # Change JSON format to match https://crate.io/docs/reference/sql/reference/copy_from.html
        with open(output_file_json, "wt") as fout:
            with open(output_file_json_temp, "rt") as fin:
                for line in fin:
                    fout.write(line.replace('[', '').replace(']', '').replace('},{', '}\n{'))

        # Delete temporary JSON
        os.remove(output_file_json_temp)
