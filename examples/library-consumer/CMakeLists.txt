cmake_minimum_required(VERSION 3.20)
project(IRVeilConsumer LANGUAGES C CXX)

find_package(IRVeil 0.2 CONFIG REQUIRED)

add_executable(irveil-consumer main.cpp)
target_link_libraries(irveil-consumer PRIVATE IRVeil::Core)
