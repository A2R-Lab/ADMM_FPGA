#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>
#include "ADMM.h"
int main(int argc,char**argv) {
    if(argc!=2 && argc!=3) return 2;
    const int count = argc==3 ? std::stoi(argv[2]) : 5;
    if(count<1 || count>256) return 2;
    std::ifstream input(argv[1]);
    for(int i=0;i<count;++i) {
        std::string line;
        if(!(input>>line)) return 3;
        ap_uint<418> state(line.c_str(),16);
        ap_uint<128> result;
        ADMM_solver(state,result);
        for(int j=3;j>=0;--j)
            std::cout<<std::hex<<std::setw(8)<<std::setfill('0')<<result.range(j*32+31,j*32).to_uint();
        std::cout<<'\n';
    }
}
