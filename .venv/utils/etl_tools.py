import os
import requests
import pandas as pd


class ETLTools:
    def __init__(self):
        pass    
    
    def extract_load(self,url:str, output_folder:str, format:str):
        """
        This tool extracts data from the API(URL) & Loads it into the desired location (output_folder)
        
        Args:
            url(str) : The API endpoint from which to extract data
            output_folder(str) : The folder where extracted data will be saved
        
        Returns:
            str: A message indicating the succes or failure of the operation
        """
        
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        output_folder=os.path.join(project_root,output_folder)
        
        try:
            response=requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            filename = os.path.join(output_folder, f"extracted_data.{format}")
            os.makedirs(output_folder, exist_ok=True)
            
            df=pd.json_normalize(data)
            if format=="csv":
                df.to_csv(filename, index=False)
            elif format=="json":
                df.to_json(filename, orient="records", lines=True)
            elif format=="parquet":
                df.to_parquet(filename, index=False)
            else:
                return f"Unsupported Format:{format}" 
            
            return f"Data Successfully extracted and saved to {filename}"
        
        except requests.exceptions.RequestException as e:
            return f"Failed to extract data:{e}"
        

    def transform_load_context(self,file_path:str):
        """
        This tool Transforms the data from the specified file and loads it into the desired location 
        (output_folder).
        Arges:
            file_path:(str)=The path to the file containing the data to transform
            output_folder:str=The Path where the transformed data will be saved.
        Returns:
            str: A message containg the Ouput success or failure of the operation
        """
        file_format=os.path.splitext(file_path)[1].lower()
        if file_format==".csv":
            df=pd.read_csv(file_path)
        elif file_format==".json":
             df=pd.read_json(file_path,lines=True)
        elif file_format==".parquet":
            df=pd.read_parquet(file_path) 
        else:
            return f"Invalid file format:{file_format}"
        
        top_3_rows=str(df.head(3))
        return top_3_rows
            

    def execute_code(self,code:str):
        """
        This Code executes the provided codes and returns The Output 
        
        Args:
            code:str = The code To be executed
        Returns:
            str: The Output of the executed code or Error if something happens
        """
        try:
            exec(code)
            return "Code Exexcuted Successfully"
        except Exception as e:
            return f"Failed To Execute Code:{e}"



def run_transform(obj):
    file_name = input("Enter File path: ")
    path = "C:\\AI Agent Project\\.venv\\data\\extracted_folder\\" + file_name
    print(obj.transform_load_context(path))


if __name__ == "__main__":
    obj = ETLTools()

    print("What would you like to do?")
    print("1. Extract data")
    print("2. Transform data")
    print("3. Exit")
    choice = input("Enter your choice (1/2/3): ").strip()

    if choice == "1":
        url = input("Url: ")
        output_folder = input("Output Folder: ")
        formats = input("Format: ")
        print(obj.extract_load(url, output_folder, formats))

        # After extracting, ask whether to transform
        next_step = input("Do you want to transform the data now? (y/n): ").strip().lower()
        if next_step == "y":
            run_transform(obj)
        else:
            print("Skipping transformation. Done.")

    elif choice == "2":
        # Transform without extracting first
        run_transform(obj)

    elif choice == "3":
        print("Exiting.")

    else:
        print("Invalid choice. Please enter 1, 2 or 3.")