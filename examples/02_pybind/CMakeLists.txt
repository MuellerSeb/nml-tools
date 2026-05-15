cmake_minimum_required(VERSION 3.26)
project(nml_pybind_example LANGUAGES C Fortran)

find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)

if(DEFINED SKBUILD_STATE AND "${SKBUILD_STATE}" MATCHES "editable")
  set(package_install_dir "${CMAKE_CURRENT_SOURCE_DIR}/src/nml_pybind_example")
else()
  set(package_install_dir "nml_pybind_example")
endif()

execute_process(
  COMMAND "${Python_EXECUTABLE}"
    -c "import numpy, pathlib as p; print(p.Path(numpy.get_include()).as_posix())"
  OUTPUT_VARIABLE NUMPY_INCLUDE_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
execute_process(
  COMMAND "${Python_EXECUTABLE}"
    -c "import numpy.f2py as f, pathlib as p; print(p.Path(f.get_include()).as_posix())"
  OUTPUT_VARIABLE F2PY_INCLUDE_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
)

set(f2py_module_name "f2py_config")
set(f2py_module_name_c "${CMAKE_CURRENT_BINARY_DIR}/${f2py_module_name}module.c")
set(f2py_module_name_f "${CMAKE_CURRENT_BINARY_DIR}/${f2py_module_name}-f2pywrappers2.f90")
set(f2py_fortranobject "${F2PY_INCLUDE_DIR}/fortranobject.c")

set(generated_dir "${CMAKE_CURRENT_SOURCE_DIR}/generated")
set(fortran_dir "${CMAKE_CURRENT_SOURCE_DIR}/fortran")
set(fortran_generated_dir "${fortran_dir}/generated")
set(f2py_dir "${CMAKE_CURRENT_SOURCE_DIR}/f2py")
set(f2py_generated_dir "${f2py_dir}/generated")
set(f2py_interface_sources
  "${f2py_generated_dir}/f2py_config.f90"
  "${f2py_dir}/f2py_config_store.f90"
)
set(config_library_sources
  "${fortran_generated_dir}/nml_helper.f90"
  "${fortran_generated_dir}/nml_config.f90"
  "${fortran_dir}/config_store.f90"
)
set(f2py_fortran_sources
  "${f2py_generated_dir}/f2py_config.f90"
  "${f2py_dir}/f2py_config_store.f90"
)

add_library(nml_pybind_config STATIC ${config_library_sources})
set_target_properties(nml_pybind_config PROPERTIES
  Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/mod"
  POSITION_INDEPENDENT_CODE ON
)
target_include_directories(nml_pybind_config PUBLIC
  "${CMAKE_CURRENT_BINARY_DIR}/mod"
)

add_custom_command(
  OUTPUT "${f2py_module_name_c}" "${f2py_module_name_f}"
  COMMAND "${Python_EXECUTABLE}" -m numpy.f2py
    -m "${f2py_module_name}"
    ${f2py_interface_sources}
    --lower
    --f2cmap "${f2py_generated_dir}/.f2py_f2cmap"
  WORKING_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
  DEPENDS
    ${f2py_interface_sources}
    nml_pybind_config
  VERBATIM
)

python_add_library(${f2py_module_name}
  MODULE WITH_SOABI
  "${f2py_module_name_c}"
  "${f2py_fortranobject}"
  "${f2py_module_name_f}"
  ${f2py_fortran_sources}
)

target_link_libraries(${f2py_module_name} PRIVATE nml_pybind_config)
target_include_directories(${f2py_module_name} PRIVATE
  "${F2PY_INCLUDE_DIR}"
  "${NUMPY_INCLUDE_DIR}"
  "${CMAKE_CURRENT_BINARY_DIR}/mod"
)
set_target_properties(${f2py_module_name} PROPERTIES
  Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/mod"
)

install(TARGETS ${f2py_module_name} DESTINATION "${package_install_dir}")
