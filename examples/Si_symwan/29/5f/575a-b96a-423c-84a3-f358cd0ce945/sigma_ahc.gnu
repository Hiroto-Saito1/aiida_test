set terminal pdf enhanced color font ",20"
set output 'sigma_ahc.pdf'
set key samplen 0.8
set ylabel offset 0.0,0
set xrange [  -0.60000:   0.60000]
set xlabel "Energy (eV)"
set ylabel "AHC (S/cm)"
#plot 'sigma_ahc_eta5.00meV.txt' u 1:2 w l title '\sigma_{xy}' lc rgb 'red' lw 4, \
'sigma_ahc_eta5.00meV.txt' u 1:3 w l title '\sigma_{yz}' lc rgb 'blue' lw 4, \
'sigma_ahc_eta5.00meV.txt' u 1:4 w l title '\sigma_{zx}' lc rgb 'orange' lw 4 
plot 'sigma_ahc_eta5.00meV.txt' u 1:2 w l title '{/Symbol s}_{xy}' lc rgb 'red' lw 4, \
'sigma_ahc_eta5.00meV.txt' u 1:3 w l title '{/Symbol s}_{yz}' lc rgb 'blue' lw 4, \
'sigma_ahc_eta5.00meV.txt' u 1:4 w l title '{/Symbol s}_{zx}' lc rgb 'orange' lw 4 
