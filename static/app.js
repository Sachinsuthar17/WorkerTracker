
// Charts with exact-ish data from screenshots
function barChart(el, labels, data, opts={}){
  const ctx = document.getElementById(el);
  if(!ctx) return;
  new Chart(ctx, {
    type:'bar',
    data:{labels, datasets:[{data, backgroundColor:'#15d4e0', borderWidth:0}]},
    options:Object.assign({
      responsive:true,
      maintainAspectRatio:false,
      scales:{y:{beginAtZero:true, grid:{color:'#1f2f3b'}, ticks:{color:'#9fb2bf'}}, x:{grid:{display:false}, ticks:{color:'#9fb2bf'}}},
      plugins:{legend:{display:false}}
    }, opts)
  });
}
function doughnutChart(el, labels, data){
  const ctx = document.getElementById(el);
  if(!ctx) return;
  new Chart(ctx, {
    type:'doughnut',
    data:{labels, datasets:[{data, backgroundColor:['#15d4e0','#f59e0b','#ef4444','#22c55e']}]},
    options:{plugins:{legend:{labels:{color:'#c7d6df'}}}}
  });
}
