// Simple front-end only demo: login -> dashboard, role controls, charts and card updates.
// Drop these 3 files into same folder and open login.html.

document.addEventListener('DOMContentLoaded', ()=> {
  const loginForm = document.getElementById('loginForm');
  if(loginForm){
    loginForm.addEventListener('submit', (e)=>{
      e.preventDefault();
      const role = document.getElementById('role').value;
      const username = document.getElementById('username').value.trim() || 'user';
      const password = document.getElementById('password').value.trim();
      if(!username || !password){ alert('Enter username & password'); return; }
      localStorage.setItem('bio_user_role', role);
      localStorage.setItem('bio_user_name', username);
      window.location.href = 'dashboard.html';
    });
    return;
  }

  // Dashboard page init
  if(location.pathname.includes('dashboard.html') || location.href.endsWith('dashboard.html')){
    const role = localStorage.getItem('bio_user_role') || 'guest';
    const username = localStorage.getItem('bio_user_name') || 'User';
    document.getElementById('welcomeUser').innerText = `${username} (${role})`;
    document.getElementById('userRoleLabel').innerText = role;

    // Hide sidebar items based on role
    if(role === 'staff'){
      // staff: hide Backup & Settings & Manage Staff
      document.querySelectorAll('.nav-item').forEach(li=>{
        const k = li.dataset.key;
        if(k==='backup' || k==='settings' || k==='staff') li.style.display = 'none';
      });
    } else if(role === 'cashier'){
      // cashier: only POS allowed
      document.querySelectorAll('.nav-item').forEach(li=>{
        if(li.dataset.key !== 'pos') li.style.display = 'none';
      });
    }

    // Sidebar collapse
    document.getElementById('collapseBtn').addEventListener('click', ()=>{
      const sb = document.getElementById('sidebar');
      const isCollapsed = sb.classList.toggle('collapsed');
      document.querySelector('.page').style.marginLeft = isCollapsed ? '80px' : '260px';
      // small tweak: hide labels when collapsed
      document.querySelectorAll('.nav-label').forEach(n=> n.style.display = isCollapsed ? 'none' : 'inline');
      document.querySelectorAll('.nav-ico').forEach(n=> n.style.marginRight = isCollapsed ? '0' : '12px');
    });

    // sample demo data
    const sales = [120,150,90,200,180,220,160];
    const inv = [120, 15, 8];

    // update cards
    document.getElementById('val-sales').innerText = sales.reduce((a,b)=>a+b,0);
    document.getElementById('val-products').innerText = inv[0];
    document.getElementById('val-expiry').innerText = inv[1];
    document.getElementById('val-lowstock').innerText = inv[2];

    // charts
    const ctx1 = document.getElementById('salesChart').getContext('2d');
    new Chart(ctx1, {
      type: 'line',
      data: {
        labels: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],
        datasets:[{
          label: 'Sales',
          data: sales,
          tension:0.3,
          borderColor:'#4e73df',
          backgroundColor:'rgba(78,115,223,0.12)',
          fill:true,
        }]
      },
      options:{plugins:{legend:{display:false}}, responsive:true}
    });

    const ctx2 = document.getElementById('inventoryChart').getContext('2d');
    new Chart(ctx2, {
      type:'bar',
      data:{
        labels:['Products','Near Expiry','Low Stock'],
        datasets:[{data:inv, backgroundColor:['#1cc88a','#f6c23e','#e74a3b']}]
      },
      options:{plugins:{legend:{display:false}}, responsive:true}
    });
  }
});

function logout(){
  localStorage.removeItem('bio_user_role');
  localStorage.removeItem('bio_user_name');
  window.location.href = 'login.html';
}
